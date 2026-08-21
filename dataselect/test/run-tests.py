#!/usr/bin/env python3
"""Test suite for dataselect, exercising the documented command line usage.

Input data is taken from ../libmseed/test/data, no test data is stored here.
Run directly or via 'make test' from the parent directory.
"""

import os
import re
import shutil
import struct
import subprocess
import sys
import unittest
import datetime

TESTDIR = os.path.dirname(os.path.abspath(__file__))
DATASELECT = os.path.join(TESTDIR, os.pardir, "dataselect")
COMPARE = os.path.join(TESTDIR, "compare-series")
DATA = os.path.join(TESTDIR, os.pardir, "libmseed", "test", "data")
TMP = os.path.join(TESTDIR, "test-tmp")

# Inputs used by the tests, all 4-record files unless noted
V2 = os.path.join(DATA, "reference-testdata-steim2.mseed2")
V3 = os.path.join(DATA, "reference-testdata-steim2.mseed3")
NSEC = os.path.join(DATA, "reference-testdata-nsec.mseed3")  # 12 records, extra headers

# Time window falling inside the first and last records of V2/V3 and NSEC
WINDOW = ["-ts", "2012-05-12T00:00:03.0", "-te", "2012-05-12T00:00:10.0"]

# miniSEED 3 fixed section field offsets, from libmseed/mseedformat.h
MS3_ENCODING = 15
MS3_CRC = 28
MS3_PUBVERSION = 32
MS3_SIDLENGTH = 33
MS3_EXTRALENGTH = 34
MS3_DATALENGTH = 36
MS3_YEAR = 8
MS3_HEADERLEN = 40


def run(*args, stdin_path=None):
    """Run dataselect, returning (returncode, stdout, stderr) with output as bytes.

    The return code is taken directly from the process, never inferred from a
    pipeline, where it would report the wrong command.
    """
    proc = subprocess.run(
        [DATASELECT] + [str(a) for a in args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout, proc.stderr


def wrote(output):
    """Return (bytes, records) from the -v 'Wrote N bytes of M records' line.

    Takes the combined output, dataselect writes normal log lines to stdout and
    diagnostics to stderr.
    """
    match = re.search(rb"Wrote (\d+) bytes of (\d+) records", output)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def crc32c(data):
    """CRC-32C (Castagnoli), needed for crafted records, zlib only has CRC-32."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def records3(path):
    """Parse a miniSEED 3 file into a list of per-record dictionaries."""
    with open(path, "rb") as handle:
        data = handle.read()

    recs = []
    offset = 0
    while offset < len(data):
        if data[offset : offset + 2] != b"MS":
            raise ValueError("not miniSEED 3 at offset %d of %s" % (offset, path))

        sidlen = data[offset + MS3_SIDLENGTH]
        extralen = struct.unpack_from("<H", data, offset + MS3_EXTRALENGTH)[0]
        datalen = struct.unpack_from("<I", data, offset + MS3_DATALENGTH)[0]
        reclen = MS3_HEADERLEN + sidlen + extralen + datalen
        record = data[offset : offset + reclen]

        # Recompute the CRC over the record with the CRC field zeroed
        stored = struct.unpack_from("<I", record, MS3_CRC)[0]
        zeroed = bytearray(record)
        struct.pack_into("<I", zeroed, MS3_CRC, 0)

        recs.append(
            {
                "offset": offset,
                "reclen": reclen,
                "encoding": record[MS3_ENCODING],
                "pubversion": record[MS3_PUBVERSION],
                "extralength": extralen,
                "datalength": datalen,
                "sid": record[MS3_HEADERLEN : MS3_HEADERLEN + sidlen].decode(),
                "extra": record[
                    MS3_HEADERLEN + sidlen : MS3_HEADERLEN + sidlen + extralen
                ],
                "crc_ok": stored == crc32c(bytes(zeroed)),
            }
        )
        offset += reclen

    return recs


def craft3(src, dst, **fields):
    """Copy a miniSEED 3 file patching header fields, recomputing each CRC.

    Supported fields: year, encoding, sid (must be the same length as the original).
    """
    recs = records3(src)
    with open(src, "rb") as handle:
        data = handle.read()

    out = bytearray()
    for rec in recs:
        record = bytearray(data[rec["offset"] : rec["offset"] + rec["reclen"]])

        if "year" in fields:
            struct.pack_into("<H", record, MS3_YEAR, fields["year"])
        if "encoding" in fields:
            record[MS3_ENCODING] = fields["encoding"]
        if "sid" in fields:
            sidlen = len(rec["sid"])
            newsid = fields["sid"]
            if len(newsid) != sidlen:
                raise ValueError(
                    "replacement sid must be %d bytes, got %d" % (sidlen, len(newsid))
                )
            record[MS3_HEADERLEN : MS3_HEADERLEN + sidlen] = newsid.encode()

        struct.pack_into("<I", record, MS3_CRC, 0)
        struct.pack_into("<I", record, MS3_CRC, crc32c(bytes(record)))
        out += record

    with open(dst, "wb") as handle:
        handle.write(bytes(out))

    return dst


def v2_records(path):
    """Split a fixed length miniSEED 2 file into records.

    The record length is taken from dataselect rather than by walking blockettes.
    """
    _, out, err = run("-v", "-v", path, "-o", os.devnull)
    lengths = set(
        int(m) for m in re.findall(rb"Read record length of (\d+) bytes", out + err)
    )
    if len(lengths) != 1:
        raise ValueError("expected a uniform record length, got %s" % sorted(lengths))

    reclen = lengths.pop()
    with open(path, "rb") as handle:
        data = handle.read()

    return [data[i : i + reclen] for i in range(0, len(data), reclen)]


def v2_block_size(record):
    """Return the Blockette 1000 record length encoded in a miniSEED 2 record."""
    first_blockette = struct.unpack(">H", record[46:48])[0]
    return 1 << record[first_blockette + 6]


def mseed2_samprate(record):
    """Sample rate in Hz from a miniSEED 2 fixed header."""
    factor, multiplier = struct.unpack_from(">hh", record, 32)
    if factor > 0 and multiplier > 0:
        return float(factor * multiplier)
    if factor > 0 and multiplier < 0:
        return -float(factor) / multiplier
    if factor < 0 and multiplier > 0:
        return -float(multiplier) / factor
    if factor < 0 and multiplier < 0:
        return 1.0 / (factor * multiplier)
    return 0.0


def mseed2_start(record):
    """Start time of a miniSEED 2 record as datetime."""
    year, yday = struct.unpack_from(">HH", record, 20)
    fract = struct.unpack_from(">H", record, 28)[0]
    return datetime.datetime(
        year, 1, 1, record[24], record[25], record[26]
    ) + datetime.timedelta(days=yday - 1, microseconds=fract * 100)


def mseed2_with_start(record, start):
    """Return a copy of a miniSEED 2 record with a new FSDH start time."""
    rec = bytearray(record)
    yday = start.timetuple().tm_yday
    struct.pack_into(">H", rec, 20, start.year)
    struct.pack_into(">H", rec, 22, yday)
    rec[24] = start.hour
    rec[25] = start.minute
    rec[26] = start.second
    struct.pack_into(">H", rec, 28, start.microsecond // 100)
    return bytes(rec)


def mseed2_nsamp(record):
    """Number of samples in a miniSEED 2 fixed header."""
    return struct.unpack_from(">H", record, 30)[0]


def series_identical(path_a, path_b):
    """Return (ok, stderr) after comparing unpacked sample times and values."""
    proc = subprocess.run(
        [COMPARE, path_a, path_b],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode == 0, proc.stderr


def tmp(name):
    return os.path.join(TMP, name)


def size(path):
    return os.path.getsize(path)


class DataselectTest(unittest.TestCase):
    """Common assertions shared by the test groups."""

    def assert_valid_ms3(self, path):
        """Every written miniSEED 3 record must be self consistent."""
        recs = records3(path)
        self.assertGreater(len(recs), 0, "no records in %s" % path)
        for index, rec in enumerate(recs):
            self.assertTrue(
                rec["crc_ok"], "record %d of %s has a bad CRC" % (index, path)
            )
            self.assertEqual(
                rec["reclen"],
                MS3_HEADERLEN
                + len(rec["sid"])
                + rec["extralength"]
                + rec["datalength"],
                "record %d of %s has an inconsistent length" % (index, path),
            )


class Invocation(DataselectTest):
    def test_version(self):
        code, stdout, err = run("-V")
        self.assertEqual(code, 0)
        self.assertIn(b"dataselect", stdout + err)

    def test_usage(self):
        code, stdout, err = run("-h")
        self.assertEqual(code, 0)
        self.assertIn(b"Usage", stdout + err)

    def test_format_usage_documents_codes(self):
        code, stdout, err = run("-H")
        self.assertEqual(code, 0)
        text = stdout + err
        # Every archive layout code should be documented
        for code_char in b"nslcYyjHMSNqvLrR":
            self.assertIn(
                b"  %c : " % code_char,
                text,
                "format code '%c' is not documented" % code_char,
            )
        # 'F' was replaced by 'N' and is no longer implemented
        self.assertNotIn(b"  F : ", text)


class InputForms(DataselectTest):
    def test_read_v2(self):
        out = tmp("v2.mseed")
        code, stdout, err = run("-v", V2, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (2048, 4))

    def test_read_v3(self):
        out = tmp("v3.mseed")
        code, stdout, err = run("-v", V3, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))
        self.assert_valid_ms3(out)

    def test_passthrough_is_byte_identical(self):
        for source in (V2, V3):
            out = tmp("copy.mseed")
            code, _, _ = run(source, "-o", out)
            self.assertEqual(code, 0)
            with open(source, "rb") as a, open(out, "rb") as b:
                self.assertEqual(
                    a.read(), b.read(), "%s was not copied verbatim" % source
                )

    def test_byte_range(self):
        out = tmp("range.mseed")
        code, stdout, err = run("-v", "%s@0-1014" % V3, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1014, 2))

    def test_list_file(self):
        listfile = tmp("filelist.txt")
        with open(listfile, "w") as handle:
            handle.write("%s\n%s\n" % (V3, V2))

        out = tmp("list.mseed")
        code, stdout, err = run("-v", "@%s" % listfile, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836 + 2048, 8))

    def test_skip_non_miniseed(self):
        """-snd skips leading non-miniSEED, without it the read is an error."""
        mixed = tmp("mixed.mseed")
        with open(mixed, "wb") as handle:
            handle.write(b"GARBAGE-NOT-MINISEED-PADDING-XXXX")
            with open(V3, "rb") as source:
                handle.write(source.read())

        code, stdout, err = run("-v", "-snd", mixed, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

        code, _, _ = run(mixed, "-o", os.devnull)
        self.assertEqual(code, 1)


class Selection(DataselectTest):
    def test_time_window(self):
        code, stdout, err = run("-v", *WINDOW, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1521, 3))

    def test_window_start_on_record_end(self):
        """-ts on the last sample of a record leaves that sample, not the record."""
        out = tmp("start-bound.mseed")
        # 00:00:06.15 is the last sample of the first record of V3
        code, stdout, err = run(
            "-v", "-v", "-v", "-Ps", "-ts", "2012-05-12T00:00:06.15", V3, "-o", out
        )
        self.assertEqual(code, 0)
        self.assertIn(b"Removing 246 samples from the start", stdout + err)
        self.assertEqual(size(out), 1452)
        self.assert_valid_ms3(out)

    def test_window_end_on_record_start(self):
        """-te on the first sample of a record leaves that sample, not the record."""
        out = tmp("end-bound.mseed")
        # 00:00:11.35 is the first sample of the last record of V3
        code, stdout, err = run(
            "-v", "-v", "-v", "-Ps", "-te", "2012-05-12T00:00:11.35", V3, "-o", out
        )
        self.assertEqual(code, 0)
        self.assertIn(b"Removing 44 samples from the end", stdout + err)
        self.assertEqual(size(out), 1644)
        self.assert_valid_ms3(out)

    def test_selection_file(self):
        selection = tmp("selection.txt")
        with open(selection, "w") as handle:
            handle.write("#SourceID\nFDSN:XX_TEST__B_H_Z\n")

        code, stdout, err = run("-v", "-s", selection, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_match(self):
        code, stdout, err = run("-v", "-m", "XX_TEST", V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_match_selects_nothing(self):
        """A match pattern that selects no data is not an error."""
        code, stdout, err = run("-v", "-m", "ZZ_NOSUCH", V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertIn(b"No data selected", stdout + err)

    def test_match_multiple(self):
        other = craft3(V3, tmp("other_match.mseed3"), sid="FDSN:YY_ABCD__B_H_Z")
        combined = tmp("two_sids_match.mseed3")
        with open(combined, "wb") as handle:
            for path in (V3, other):
                with open(path, "rb") as part:
                    handle.write(part.read())

        code, stdout, err = run(
            "-v", "-m", "XX_TEST", "-m", "YY_ABCD", combined, "-o", os.devnull
        )
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (3672, 8))

    def test_match_multiple_one_matches(self):
        code, stdout, err = run(
            "-v", "-m", "ZZ_NOSUCH", "-m", "XX_TEST", V3, "-o", os.devnull
        )
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_match_multiple_with_time_window(self):
        code, stdout, err = run(
            "-v", "-m", "ZZ_NOSUCH", "-m", "XX_TEST", *WINDOW, V3, "-o", os.devnull
        )
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1521, 3))

    def test_reject(self):
        other = craft3(V3, tmp("other_sid.mseed3"), sid="FDSN:YY_ABCD__B_H_Z")
        combined = tmp("two_sids.mseed3")
        with open(combined, "wb") as handle:
            for path in (V3, other):
                with open(path, "rb") as part:
                    handle.write(part.read())

        code, stdout, err = run("-v", "-r", "YY_ABCD", combined, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_reject_multiple(self):
        other = craft3(V3, tmp("other_sid2.mseed3"), sid="FDSN:YY_ABCD__B_H_Z")
        combined = tmp("two_sids2.mseed3")
        with open(combined, "wb") as handle:
            for path in (V3, other):
                with open(path, "rb") as part:
                    handle.write(part.read())

        code, stdout, err = run(
            "-v", "-r", "XX_TEST", "-r", "YY_ABCD", combined, "-o", os.devnull
        )
        self.assertEqual(code, 0)
        self.assertIn(b"No data selected", stdout + err)

    def test_reject_overrides_match(self):
        code, stdout, err = run(
            "-v", "-m", "XX_TEST", "-r", "XX_TEST", V3, "-o", os.devnull
        )
        self.assertEqual(code, 0)
        self.assertIn(b"No data selected", stdout + err)

    def test_reject_output_valid(self):
        other = craft3(V3, tmp("other_sid3.mseed3"), sid="FDSN:YY_ABCD__B_H_Z")
        combined = tmp("two_sids3.mseed3")
        with open(combined, "wb") as handle:
            for path in (V3, other):
                with open(path, "rb") as part:
                    handle.write(part.read())

        out = tmp("reject.mseed")
        code, _, _ = run("-r", "YY_ABCD", combined, "-o", out)
        self.assertEqual(code, 0)
        self.assert_valid_ms3(out)


class Pruning(DataselectTest):
    """Overlap is synthesized by reading the same file twice."""

    def test_no_pruning_keeps_duplicates(self):
        code, stdout, err = run("-v", V3, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (3672, 8))

    def test_prune_record_level(self):
        code, stdout, err = run("-v", "-Pr", V3, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_prune_sample_level(self):
        out = tmp("prune.mseed")
        code, stdout, err = run("-v", "-Ps", V3, V3, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))
        self.assert_valid_ms3(out)

    def test_prune_edges_only(self):
        out = tmp("edges.mseed")
        code, _, _ = run("-Pe", *WINDOW, V3, "-o", out)
        self.assertEqual(code, 0)
        self.assertEqual(size(out), 1201)
        self.assert_valid_ms3(out)

    def test_equal_versions(self):
        code, stdout, err = run("-v", "-E", "-Ps", V3, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_file_order_priority(self):
        code, stdout, err = run("-v", "-F", "-Ps", V3, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertEqual(wrote(stdout + err), (1836, 4))

    def test_tolerances(self):
        """A generous -tt/-rt must not push record bounds outside the selection."""
        out = tmp("tolerance.mseed")
        code, _, err = run("-Ps", "-tt", "5", "-rt", "0.1", *WINDOW, V3, V3, "-o", out)
        self.assertEqual(code, 0, "unexpected failure: %s" % err.decode())
        self.assertEqual(size(out), 1201)
        self.assert_valid_ms3(out)


class Output(DataselectTest):
    def test_output_to_stdout(self):
        code, out, _ = run(V3, "-o", "-")
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1836)

    def test_append_output(self):
        out = tmp("append.mseed")
        run("+o", out, V3)
        first = size(out)
        run("+o", out, V3)
        self.assertEqual(first, 1836)
        self.assertEqual(size(out), 2 * first)

    def test_quality_indicator_v2(self):
        """-Q sets the v2 data quality indicator, including on re-packed records."""
        for option, indicator in (("R", b"R"), ("D", b"D"), ("Q", b"Q"), ("M", b"M")):
            out = tmp("quality.mseed")
            code, _, _ = run("-Q", option, "-Ps", *WINDOW, V2, "-o", out)
            self.assertEqual(code, 0)
            for index, record in enumerate(v2_records(out)):
                self.assertEqual(
                    record[6:7],
                    indicator,
                    "-Q %s: record %d has quality %r" % (option, index, record[6:7]),
                )

    def test_publication_version_v3(self):
        for option, pubversion in (("R", 1), ("D", 2), ("Q", 3), ("M", 4)):
            out = tmp("pubversion.mseed")
            code, _, _ = run("-Q", option, "-Ps", *WINDOW, V3, "-o", out)
            self.assertEqual(code, 0)
            for index, rec in enumerate(records3(out)):
                self.assertEqual(
                    rec["pubversion"],
                    pubversion,
                    "-Q %s: record %d has pubversion %d"
                    % (option, index, rec["pubversion"]),
                )
            self.assert_valid_ms3(out)


class BlockSize(DataselectTest):
    """-B re-packs output records to a requested miniSEED block/record length."""

    V2_4096 = os.path.join(DATA, "reference-testdata-defaults.mseed2")

    def test_usage_documents_B(self):
        code, stdout, err = run("-h")
        self.assertEqual(code, 0)
        self.assertIn(b"-B bytes", stdout + err)

    def test_invalid_block_size(self):
        for value in ("0", "100", "513", "200000"):
            code, _, err = run("-B", value, V2, "-o", os.devnull)
            self.assertEqual(code, 1, "expected failure for -B %s" % value)
            self.assertIn(b"Invalid miniSEED block size", err)

    def test_v2_4096_to_512(self):
        out = tmp("block512.mseed")
        code, _, err = run("-B", "512", self.V2_4096, "-o", out)
        self.assertEqual(code, 0, err.decode())
        self.assertEqual(size(out) % 512, 0)
        recs = v2_records(out)
        self.assertGreater(len(recs), 1)
        for rec in recs:
            self.assertEqual(len(rec), 512)
            self.assertEqual(v2_block_size(rec), 512)
        ok, cerr = series_identical(self.V2_4096, out)
        self.assertTrue(ok, cerr.decode())

    def test_v2_512_to_4096(self):
        out = tmp("block4096.mseed")
        code, _, err = run("-B", "4096", V2, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        self.assertGreater(len(recs), 0)
        for rec in recs:
            self.assertEqual(len(rec), 4096)
            self.assertEqual(v2_block_size(rec), 4096)
        ok, cerr = series_identical(V2, out)
        self.assertTrue(ok, cerr.decode())

    def test_v3_max_record_length(self):
        out = tmp("block512_v3.mseed")
        code, _, err = run("-B", "512", V3, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = records3(out)
        self.assertGreater(len(recs), 0)
        for rec in recs:
            self.assertLessEqual(rec["reclen"], 512)
        self.assert_valid_ms3(out)
        ok, cerr = series_identical(V3, out)
        self.assertTrue(ok, cerr.decode())

    def test_block_size_with_trim(self):
        out = tmp("block512_trim.mseed")
        code, _, err = run("-B", "512", "-Ps", *WINDOW, V2, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        self.assertGreater(len(recs), 0)
        for rec in recs:
            self.assertEqual(len(rec), 512)
            self.assertEqual(v2_block_size(rec), 512)

        trimmed = tmp("trim_only.mseed")
        code, _, err = run("-Ps", *WINDOW, V2, "-o", trimmed)
        self.assertEqual(code, 0, err.decode())
        ok, cerr = series_identical(trimmed, out)
        self.assertTrue(ok, cerr.decode())

    def test_repack_preserves_numeric_encodings(self):
        for name in (
            "reference-testdata-int16.mseed2",
            "reference-testdata-int32.mseed2",
            "reference-testdata-float32.mseed2",
            "reference-testdata-float64.mseed2",
            "reference-testdata-steim1.mseed2",
            "reference-testdata-nsec.mseed3",
        ):
            source = os.path.join(DATA, name)
            out = tmp("repack-%s" % name)
            code, _, err = run("-B", "512", source, "-o", out)
            self.assertEqual(code, 0, "%s: %s" % (name, err.decode()))
            ok, cerr = series_identical(source, out)
            self.assertTrue(ok, "%s: %s" % (name, cerr.decode()))

    def test_unsupported_encoding_is_an_error(self):
        crafted = craft3(V3, tmp("int24_block.mseed3"), encoding=2)
        out = tmp("int24_block_out.mseed")
        code, _, err = run("-B", "512", crafted, "-o", out)
        self.assertEqual(code, 1)
        self.assertIn(b"ERROR", err)

    def test_legacy_encoding_is_an_error(self):
        source = os.path.join(DATA, "testdata-encoding-CDSN.mseed2")
        code, _, err = run("-B", "512", source, "-o", tmp("cdsn.mseed"))
        self.assertEqual(code, 1)
        self.assertIn(b"ERROR", err)

    def test_block_size_too_small_for_headers(self):
        """nsec extra headers are larger than a 256-byte record."""
        source = os.path.join(DATA, "reference-testdata-nsec.mseed3")
        code, _, err = run("-B", "256", source, "-o", tmp("tiny.mseed"))
        self.assertEqual(code, 1)
        self.assertIn(b"ERROR", err)

    def test_v2_sequence_increments_when_split(self):
        out = tmp("seq.mseed")
        code, _, err = run("-B", "512", self.V2_4096, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        self.assertGreater(len(recs), 1)
        seqs = [int(rec[:6]) for rec in recs]
        self.assertEqual(seqs[0], 1)
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_v2_sequence_is_contiguous_across_input_records(self):
        """-B assigns sequences in write order, not from each input record."""
        out = tmp("seq_multi.mseed")
        code, _, err = run("-B", "512", V2, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        self.assertGreater(len(recs), 1)
        seqs = [int(rec[:6]) for rec in recs]
        self.assertEqual(seqs, list(range(1, len(recs) + 1)))

    def test_v2_sequence_restarts_when_archive_file_changes(self):
        """Each archive file starts sequences at 000001; they do not continue."""
        root = tmp("seq_files")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        code, _, err = run(
            "-B",
            "512",
            self.V2_4096,
            "-A",
            os.path.join(root, "%n.%s.%l.%c.%H.%M.%S.%N"),
        )
        self.assertEqual(code, 0, err.decode())

        paths = []
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                paths.append(os.path.join(dirpath, name))
        self.assertGreater(len(paths), 1)

        for path in paths:
            recs = v2_records(path)
            self.assertGreater(len(recs), 0, path)
            seqs = [int(rec[:6]) for rec in recs]
            self.assertEqual(
                seqs,
                list(range(1, len(seqs) + 1)),
                "%s sequences were %s" % (path, seqs),
            )

    def test_v2_sequence_restarts_per_channel(self):
        """Each SourceID gets its own 000001, 000002, ... sequence."""
        source = os.path.join(DATA, "testdata-3channel-signal.mseed2")
        out = tmp("seq_3ch.mseed")
        code, _, err = run("-B", "512", source, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        by_channel = {}
        for rec in recs:
            channel = rec[15:18]
            by_channel.setdefault(channel, []).append(int(rec[:6]))
        self.assertGreaterEqual(len(by_channel), 2)
        for channel, seqs in by_channel.items():
            self.assertEqual(
                seqs,
                list(range(1, len(seqs) + 1)),
                "channel %s sequences were %s" % (channel, seqs),
            )

    def test_summary_samples_match_when_repacked(self):
        orig_sum = tmp("sum_orig.txt")
        new_sum = tmp("sum_new.txt")
        data = tmp("sum_data.mseed")
        self.assertEqual(run("-out", orig_sum, self.V2_4096, "-o", os.devnull)[0], 0)
        self.assertEqual(
            run("-B", "512", "-out", new_sum, self.V2_4096, "-o", data)[0], 0
        )

        def fields(path):
            with open(path, "r") as handle:
                line = handle.read().strip().split("|")
            return line

        orig = fields(orig_sum)
        new = fields(new_sum)
        # SourceID, pubversion, start, end, samples must match; bytes change
        self.assertEqual(orig[0], new[0])
        self.assertEqual(orig[1], new[1])
        self.assertEqual(orig[2], new[2])
        self.assertEqual(orig[3], new[3])
        self.assertEqual(orig[5], new[5], "sample count changed after -B")
        self.assertNotEqual(orig[4], new[4], "byte count should change with block size")

    def test_archive_time_layout_preserves_series(self):
        """Split records with time in the archive path still form the original series."""
        root = tmp("archive_time")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        code, _, err = run(
            "-B",
            "512",
            self.V2_4096,
            "-A",
            os.path.join(root, "%n.%s.%l.%c.%H.%M.%S.%N"),
        )
        self.assertEqual(code, 0, err.decode())

        paths = []
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                paths.append(os.path.join(dirpath, name))
        paths.sort()
        self.assertGreater(len(paths), 1)

        combined = tmp("archive_time_combined.mseed")
        with open(combined, "wb") as handle:
            for path in paths:
                with open(path, "rb") as part:
                    handle.write(part.read())

        ok, cerr = series_identical(self.V2_4096, combined)
        self.assertTrue(ok, cerr.decode())

    def test_continuous_records_fill_larger_block(self):
        """Several continuous 512-byte records fill one 4096-byte record."""
        out = tmp("filled4096.mseed")
        code, _, err = run("-B", "4096", V2, "-o", out)
        self.assertEqual(code, 0, err.decode())
        recs = v2_records(out)
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(recs[0]), 4096)
        ok, cerr = series_identical(V2, out)
        self.assertTrue(ok, cerr.decode())

    def test_continuous_records_fill_512_across_input_records(self):
        """Two continuous 4096-byte records share 512-byte output records."""
        first = tmp("half1_4096.mseed")
        second = tmp("half2_4096.mseed")
        # 40 Hz: last sample of the first half at 00:00:06.0, first of the
        # second half at 00:00:06.025.  -te/-ts are inclusive sample times.
        code, _, err = run(
            "-Pe",
            "-te",
            "2012-05-12T00:00:06.0",
            "-B",
            "4096",
            self.V2_4096,
            "-o",
            first,
        )
        self.assertEqual(code, 0, err.decode())
        code, _, err = run(
            "-Pe",
            "-ts",
            "2012-05-12T00:00:06.025",
            "-B",
            "4096",
            self.V2_4096,
            "-o",
            second,
        )
        self.assertEqual(code, 0, err.decode())

        recs1 = v2_records(first)
        recs2 = v2_records(second)
        self.assertEqual(len(recs1), 1)
        self.assertEqual(len(recs2), 1)

        continuous = tmp("two_continuous.mseed2")
        with open(continuous, "wb") as handle:
            handle.write(recs1[0])
            handle.write(recs2[0])

        gapped = tmp("two_gapped.mseed2")
        with open(gapped, "wb") as handle:
            handle.write(recs1[0])
            handle.write(
                mseed2_with_start(
                    recs2[0],
                    mseed2_start(recs2[0]) + datetime.timedelta(seconds=2),
                )
            )

        split_a = tmp("half1_512.mseed")
        split_b = tmp("half2_512.mseed")
        self.assertEqual(run("-B", "512", first, "-o", split_a)[0], 0)
        self.assertEqual(run("-B", "512", second, "-o", split_b)[0], 0)
        n_separate = len(v2_records(split_a)) + len(v2_records(split_b))
        n_first_alone = mseed2_nsamp(v2_records(split_a)[0])

        out_cont = tmp("cont_512.mseed")
        code, _, err = run("-B", "512", continuous, "-o", out_cont)
        self.assertEqual(code, 0, err.decode())
        recs_cont = v2_records(out_cont)
        self.assertGreater(mseed2_nsamp(recs_cont[0]), n_first_alone)
        ok, cerr = series_identical(continuous, out_cont)
        self.assertTrue(ok, cerr.decode())

        out_gap = tmp("gap_512.mseed")
        code, _, err = run("-B", "512", gapped, "-o", out_gap)
        self.assertEqual(code, 0, err.decode())
        recs_gap = v2_records(out_gap)
        self.assertEqual(len(recs_gap), n_separate)
        self.assertEqual(mseed2_nsamp(recs_gap[0]), n_first_alone)
        ok, cerr = series_identical(gapped, out_gap)
        self.assertTrue(ok, cerr.decode())

    def test_archive_matches_single_file_when_repacked(self):
        root = tmp("archive_b")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        out = tmp("single_b.mseed")
        code, _, err = run(
            "-B",
            "512",
            self.V2_4096,
            "-o",
            out,
            "-A",
            os.path.join(root, "%n.%s.%l.%c"),
        )
        self.assertEqual(code, 0, err.decode())

        paths = []
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                paths.append(os.path.join(dirpath, name))
        self.assertEqual(len(paths), 1)
        with open(paths[0], "rb") as archived, open(out, "rb") as single:
            self.assertEqual(archived.read(), single.read())


class Archive(DataselectTest):
    def archive(self, layout, *args):
        """Write an archive and return the sorted relative paths produced."""
        root = tmp("archive")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        code, _, err = run(*(list(args) + ["-A", os.path.join(root, layout)]))
        self.assertEqual(code, 0, "archive write failed: %s" % err.decode())

        paths = []
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                paths.append(os.path.relpath(os.path.join(dirpath, name), root))
        return root, sorted(paths)

    def test_archive_matches_single_file_output(self):
        """The archive and -o paths must produce the same bytes."""
        for source in (V2, V3):
            root, paths = self.archive("%n.%s.%l.%c", source)
            self.assertEqual(paths, ["XX.TEST..BHZ"])

            single = tmp("single.mseed")
            run(source, "-o", single)
            with open(os.path.join(root, paths[0]), "rb") as a, open(single, "rb") as b:
                self.assertEqual(
                    a.read(), b.read(), "archive differs from -o for %s" % source
                )

    def test_archive_matches_output_when_repacked(self):
        """Re-packed records must be written with their new length, not the original."""
        root, paths = self.archive("%n.%s.%l.%c", "-Ps", *WINDOW, V3)
        archived = os.path.join(root, paths[0])

        single = tmp("single.mseed")
        run("-Ps", *WINDOW, V3, "-o", single)

        with open(archived, "rb") as a, open(single, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assert_valid_ms3(archived)

    def test_layout_presets(self):
        expected = {
            "-CHAN": "XX.TEST..BHZ",
            "-VCHAN": "XX.TEST..BHZ.1",
            "-QCHAN": "XX.TEST..BHZ.R",
            "-CDAY": "XX.TEST..BHZ.2012:133:00:00:00",
            "-SDAY": "XX.TEST.2012:133",
            "-BUD": os.path.join("XX", "TEST", "TEST.XX..BHZ.2012.133"),
            "-SDS": os.path.join(
                "2012", "XX", "TEST", "BHZ.D", "XX.TEST..BHZ.D.2012.133"
            ),
            "-CSS": os.path.join("2012", "133", "TEST.BHZ.2012:133:00:00:00"),
        }

        for option, relpath in expected.items():
            root = tmp("preset")
            shutil.rmtree(root, ignore_errors=True)
            os.makedirs(root)

            code, _, err = run(option, root, V3)
            self.assertEqual(code, 0, "%s failed: %s" % (option, err.decode()))
            self.assertTrue(
                os.path.isfile(os.path.join(root, relpath)),
                "%s did not produce %s" % (option, relpath),
            )

    def test_layout_format_codes(self):
        """All time, source and record codes expand into the file name."""
        layout = "%n.%s.%l.%c.%Y.%y.%j.%H.%M.%S.%N.%q.%v.%L.%r.%R.%%.%#"
        root, paths = self.archive(layout, V3)
        # The time codes are defining flags, so each record gets its own file,
        # and %L differs for the shorter final record
        self.assertEqual(
            paths,
            [
                "XX.TEST..BHZ.2012.12.133.00.00.00.000000000.R.1.507.40.40.000000.%.#",
                "XX.TEST..BHZ.2012.12.133.00.00.06.175000000.R.1.507.40.40.000000.%.#",
                "XX.TEST..BHZ.2012.12.133.00.00.08.775000000.R.1.507.40.40.000000.%.#",
                "XX.TEST..BHZ.2012.12.133.00.00.11.350000000.R.1.315.40.40.000000.%.#",
            ],
        )

    def test_long_archive_path(self):
        """An over-long expanded path is truncated, it must not crash."""
        root = tmp("longpath")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        code, _, _ = run("-A", os.path.join(root, "A" * 400 + "%n"), V3)
        self.assertLess(code, 128, "dataselect was killed by a signal")


class Logging(DataselectTest):
    SUMMARY = re.compile(
        rb"^(.*)FDSN:XX_TEST__B_H_Z\|1\|"
        rb"2012-05-12T00:00:00\.000000Z\|"
        rb"2012-05-12T00:00:12\.450000Z\|1836\|499$",
        re.M,
    )

    def test_summary_to_file(self):
        out = tmp("summary.txt")
        code, _, _ = run("-out", out, V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        with open(out, "rb") as handle:
            self.assertRegex(handle.read(), self.SUMMARY)

    def test_summary_to_stdout(self):
        code, out, _ = run("-out", "-", V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertRegex(out, self.SUMMARY)

    def test_summary_to_stderr(self):
        code, _, err = run("-out", "--", V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertRegex(err, self.SUMMARY)

    def test_summary_with_data_on_stdout(self):
        """Writing data to stdout must not suppress the summary."""
        code, out, _ = run("-out", "-", V3, "-o", "-")
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1836 + 87, "expected data followed by the summary")
        self.assertRegex(out, self.SUMMARY)

    def test_summary_prefix(self):
        code, out, _ = run("-out", "-", "-outprefix", "PFX|", V3, "-o", os.devnull)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(b"PFX|FDSN:"), out[:40])


class ExitStatus(DataselectTest):
    def test_success(self):
        code, _, _ = run(V3, "-o", os.devnull)
        self.assertEqual(code, 0)

    def test_unrecognized_input(self):
        notdata = tmp("notdata.txt")
        with open(notdata, "w") as handle:
            handle.write("this is not miniSEED\n" * 40)

        code, _, err = run(notdata, "-o", os.devnull)
        self.assertEqual(code, 1)
        self.assertIn(b"ERROR", err)

    def test_missing_input(self):
        code, _, _ = run(tmp("nosuchfile.mseed"), "-o", os.devnull)
        self.assertEqual(code, 1)

    def test_unknown_option(self):
        code, _, _ = run("-nosuchoption", V3)
        self.assertEqual(code, 1)


class Fidelity(DataselectTest):
    def test_extra_headers_retained_when_repacked(self):
        """Trimming re-packs records, the extra headers must survive it."""
        source = records3(NSEC)
        self.assertEqual(len(source), 12)
        self.assertTrue(
            all(rec["extralength"] > 0 for rec in source),
            "test input has no extra headers",
        )

        out = tmp("extraheaders.mseed")
        code, _, _ = run("-Ps", *WINDOW, NSEC, "-o", out)
        self.assertEqual(code, 0)

        result = records3(out)
        self.assertEqual(len(result), 7)
        for index, rec in enumerate(result):
            self.assertEqual(
                rec["extralength"],
                source[0]["extralength"],
                "record %d lost its extra headers" % index,
            )
        self.assert_valid_ms3(out)

    def test_output_can_be_read_back(self):
        """Anything dataselect writes it must be able to read again."""
        out = tmp("roundtrip.mseed")
        run("-Ps", *WINDOW, NSEC, "-o", out)

        again = tmp("roundtrip2.mseed")
        code, _, err = run("-v", out, "-o", again)
        self.assertEqual(code, 0, err.decode())
        self.assertEqual(size(again), size(out))


class CraftedInput(DataselectTest):
    def test_two_digit_year_of_a_century(self):
        """%y is a two digit year, a multiple of 100 must not render as three."""
        crafted = craft3(V3, tmp("year2000.mseed3"), year=2000)

        root = tmp("century")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)

        code, _, _ = run("-A", os.path.join(root, "%n.%s.%y"), crafted)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(root)), ["XX.TEST.00"])

    def test_untrimmable_record_is_written_untrimmed(self):
        """An encoding that cannot be re-packed is passed through with a warning."""
        crafted = craft3(V3, tmp("int24.mseed3"), encoding=2)

        out = tmp("untrimmed.mseed")
        code, _, err = run("-Ps", "-ts", "2012-05-12T00:00:03.0", crafted, "-o", out)

        self.assertEqual(code, 0, "an unsupported encoding is not an error")
        self.assertIn(b"Warning", err)
        self.assertEqual(
            len(records3(out)),
            len(records3(crafted)),
            "records were dropped instead of written untrimmed",
        )


def main():
    if not os.path.isfile(DATASELECT):
        sys.exit("dataselect not built, run 'make' first: %s" % DATASELECT)
    if not os.path.isfile(COMPARE):
        sys.exit("compare-series not built, run 'make test' first: %s" % COMPARE)
    if not os.path.isdir(DATA):
        sys.exit("test data not found: %s" % DATA)

    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)

    result = unittest.main(
        module=__name__, argv=[sys.argv[0], "-v"] + sys.argv[1:], exit=False
    ).result

    # Leave the working files behind when something failed, for inspection
    if result.wasSuccessful():
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("\nWorking files left in %s" % TMP)

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
