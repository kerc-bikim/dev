/***************************************************************************
 * local.h - Local -B (output record/block size) extension.
 *
 * Keep EarthScope dataselect.c close to upstream.  All -B state and
 * helpers live here / in local.c.  After an upstream merge, search
 * dataselect.c for "LOCAL" and re-apply the marked hooks.  See
 * ../UPSTREAM.md.
 ***************************************************************************/

#ifndef DATASELECT_LOCAL_H
#define DATASELECT_LOCAL_H

#include <stdint.h>

#include <libmseed.h>

/* Local release; overrides the upstream VERSION in dataselect.c. */
#ifdef VERSION
#undef VERSION
#endif
#define VERSION "4.4.0"

/* Inserted into the usage() string (C concatenates adjacent literals). */
#define LOCAL_USAGE_B                                                              \
  " -B bytes     Re-pack output to this miniSEED record/block size\n"              \
  "                Power of 2 (e.g. 512, 4096); sample times and values are unchanged\n" \
  "                miniSEED 2: exact length; miniSEED 3: maximum length\n" \
  "                Continuous traces fill records before writing; a short record is written at a gap or end\n"

/* Parse -B argument.  Returns 0 on success, -1 on invalid value. */
int local_set_blocksize (const char *arg);

/* Requested output record length, or 0 when -B was not given. */
int local_outputreclen (void);

/* Unpack/re-pack this record: sample trim and/or -B. */
int local_should_unpack (int needs_trim);

/* 1 if this encoding may be packed (always 1 when -B is off). */
int local_encoding_can_pack (int16_t encoding);

/* Log a fatal -B encoding error.  Returns 1 when the caller must return -3. */
int local_reject_encoding (const MS3Record *msr);

/* Log a fatal -B+trim encoding error.  Returns 1 when the caller must return -3. */
int local_reject_trim_encoding (const MS3Record *msr);

/* Parse/pack failure is fatal when -B was requested. */
int local_pack_fail_is_fatal (void);

/* Register writetraces() output counters so -B can count packed records. */
void local_set_counters (uint64_t *recs, uint64_t *bytes);

/* Reset per-pack write count (sequence state is kept per SourceID). */
void local_pack_begin (const uint8_t *srcbuf, uint8_t formatversion);

/* Apply -B record length to the unpacked record before msr3_pack(). */
void local_prepare_pack (MS3Record *msr);

/* Feed unpacked samples into the -B packer.  Continuous traces are
 * buffered until a record fills.  Returns 0 on success, -1 on error. */
int local_pack_feed (MS3Record *msr, nstime_t nstimetol,
                     void (*handler) (char *, int, void *), void *handlerdata,
                     MS3Record **msrslot, int8_t verbose);

/* Flush any samples still buffered by local_pack_feed(). */
int local_pack_flush (void (*handler) (char *, int, void *), void *handlerdata,
                      MS3Record **msrslot, int8_t verbose);

/* 1 if packing did not emit every sample. */
int local_incomplete_pack (int packedrecords, int64_t packedsamples,
                           const MS3Record *msr);

/* 1 if the original record must not be written after a pack failure. */
int local_discard_original (void);

/* 1 when writetraces() must not count the input record (already counted). */
int local_write_counted (void);

/* 1 when each packed record must be parsed for archive / -out. */
int local_should_parse_packed (void);

/* Stamp the next per-channel miniSEED 2 sequence (write order, from 1). */
void local_stamp_v2_sequence (uint8_t *record, int reclen, uint8_t formatversion,
                              const char *sid);

/* Count a written record (no-op for the input-record counter when -B is off). */
void local_note_write (uint64_t recsize);

#endif /* DATASELECT_LOCAL_H */
