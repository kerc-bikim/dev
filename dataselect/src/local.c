/***************************************************************************
 * local.c - Local -B (output record/block size) extension.
 *
 * Unpacks each contributing record and re-packs it to a caller-chosen
 * miniSEED record length.  Sample times and values are unchanged.
 * miniSEED 2 records are padded to the exact length; miniSEED 3 uses
 * the value as a maximum.  Input records are never merged.
 *
 * Packing failures (unsupported encoding, header larger than the
 * requested length, partial pack) are fatal: the original record is
 * not written mixed with re-packed output.
 *
 * miniSEED 2 sequence numbers are rewritten per output file and
 * SourceID in write (time) order, starting at 1 and wrapping at
 * 1000000.  A new archive file (for example a new SDS day) starts
 * again at 1.
 ***************************************************************************/

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libmseed.h>

#include "local.h"

static int outputreclen = 0; /* 0 = keep original record length */
static int wrote_this_pack = 0;
static uint64_t *totalrecsoutp = NULL;
static uint64_t *totalbytesoutp = NULL;

/* Per output-file + SourceID miniSEED 2 sequence, from 1. */
typedef struct SidSeq_s
{
  char *filekey;
  char *sid;
  int64_t next;
  struct SidSeq_s *nextsid;
} SidSeq;

static SidSeq *sidseqs = NULL;

static char *
local_dupstr (const char *s)
{
  size_t n;
  char *d;

  if (!s)
    s = "";

  n = strlen (s) + 1;
  d = (char *)malloc (n);
  if (!d)
    return NULL;

  memcpy (d, s, n);
  return d;
}

static void
local_seq_reset (void)
{
  SidSeq *p;

  while (sidseqs)
  {
    p = sidseqs;
    sidseqs = p->nextsid;
    free (p->filekey);
    free (p->sid);
    free (p);
  }
}

static int64_t
local_take_v2seq (const char *sid, const char *filekey)
{
  SidSeq *p;
  const char *sidkey = (sid && sid[0]) ? sid : "";
  const char *fkey = (filekey && filekey[0]) ? filekey : "";

  for (p = sidseqs; p; p = p->nextsid)
  {
    if (strcmp (p->sid, sidkey) == 0 && strcmp (p->filekey, fkey) == 0)
    {
      int64_t seq = p->next;
      p->next = (p->next + 1) % 1000000;
      return seq;
    }
  }

  p = (SidSeq *)malloc (sizeof (SidSeq));
  if (!p)
    return -1;

  p->filekey = local_dupstr (fkey);
  p->sid = local_dupstr (sidkey);
  if (!p->filekey || !p->sid)
  {
    free (p->filekey);
    free (p->sid);
    free (p);
    return -1;
  }

  p->next = 2;
  p->nextsid = sidseqs;
  sidseqs = p;
  return 1;
}

static int
encoding_can_pack (int16_t encoding)
{
  switch (encoding)
  {
  case DE_TEXT:
  case DE_INT16:
  case DE_INT32:
  case DE_FLOAT32:
  case DE_FLOAT64:
  case DE_STEIM1:
  case DE_STEIM2:
    return 1;
  default:
    return 0;
  }
}

int
local_set_blocksize (const char *arg)
{
  char *endptr = NULL;
  unsigned long value;

  if (!arg)
    return -1;

  value = strtoul (arg, &endptr, 10);

  if (*endptr != '\0' || value < 128 || value > 131072 || (value & (value - 1)) != 0)
  {
    ms_log (2, "Invalid miniSEED block size: %s\n", arg);
    ms_log (2, "Block size must be a power of 2 between 128 and 131072 bytes\n");
    return -1;
  }

  outputreclen = (int)value;
  return 0;
}

int
local_outputreclen (void)
{
  return outputreclen;
}

int
local_should_unpack (int needs_trim)
{
  return needs_trim || outputreclen > 0;
}

int
local_encoding_can_pack (int16_t encoding)
{
  if (outputreclen <= 0)
    return 1;

  return encoding_can_pack (encoding);
}

int
local_reject_encoding (const MS3Record *msr)
{
  char stime[32] = {0};

  if (outputreclen <= 0 || !msr)
    return 0;

  ms_nstime2timestr_n (msr->starttime, stime, sizeof (stime), ISOMONTHDAY_Z, NANO_MICRO);
  ms_log (2, "Cannot re-pack %s (%s) to %d byte records, encoding %d (%s)\n",
          msr->sid, stime, outputreclen, msr->encoding,
          ms_encodingstr (msr->encoding));
  return 1;
}

int
local_reject_trim_encoding (const MS3Record *msr)
{
  char stime[32] = {0};

  if (outputreclen <= 0 || !msr)
    return 0;

  ms_nstime2timestr_n (msr->starttime, stime, sizeof (stime), ISOMONTHDAY_Z, NANO_MICRO);
  ms_log (2, "Cannot trim and re-pack %s (%s), encoding %d (%s)\n",
          msr->sid, stime, msr->encoding, ms_encodingstr (msr->encoding));
  return 1;
}

int
local_pack_fail_is_fatal (void)
{
  return outputreclen > 0;
}

void
local_set_counters (uint64_t *recs, uint64_t *bytes)
{
  local_seq_reset ();
  totalrecsoutp = recs;
  totalbytesoutp = bytes;
}

void
local_pack_begin (const uint8_t *srcbuf, uint8_t formatversion)
{
  (void)srcbuf;
  (void)formatversion;
  wrote_this_pack = 0;
}

void
local_prepare_pack (MS3Record *msr)
{
  if (outputreclen > 0 && msr)
    msr->reclen = outputreclen;
}

int
local_incomplete_pack (int packedrecords, int64_t packedsamples, const MS3Record *msr)
{
  if (packedrecords <= 0)
    return 1;

  if (!msr)
    return 1;

  return packedsamples != msr->numsamples;
}

int
local_discard_original (void)
{
  return wrote_this_pack > 0 || outputreclen > 0;
}

int
local_write_counted (void)
{
  return outputreclen > 0;
}

int
local_should_parse_packed (void)
{
  return outputreclen > 0;
}

void
local_stamp_v2_sequence (uint8_t *record, int reclen, uint8_t formatversion,
                         const char *sid, const char *filekey)
{
  char seqstr[7];
  int64_t seq;

  if (outputreclen <= 0 || formatversion != 2 || reclen < 6 || !record)
    return;

  seq = local_take_v2seq (sid, filekey);
  if (seq < 0)
    return;

  snprintf (seqstr, sizeof (seqstr), "%06" PRId64, seq % 1000000);
  memcpy (record, seqstr, 6);
}

void
local_note_write (uint64_t recsize)
{
  wrote_this_pack++;

  if (outputreclen <= 0)
    return;

  if (totalrecsoutp)
    (*totalrecsoutp)++;
  if (totalbytesoutp)
    (*totalbytesoutp) += recsize;
}
