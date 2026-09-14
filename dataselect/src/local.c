/***************************************************************************
 * local.c - Local -B (output record/block size) extension.
 *
 * Unpacks contributing records and re-packs them to a caller-chosen
 * miniSEED record length.  Sample times and values are unchanged.
 * miniSEED 2 records are padded to the exact length; miniSEED 3 uses
 * the value as a maximum.
 *
 * Continuous samples of the same channel are buffered until a record
 * fills, then written.  A short (padded) record is written only at a
 * time gap, a stream change, or the end of output.  Overlapping
 * records are not merged.
 *
 * Packing failures (unsupported encoding, header larger than the
 * requested length, partial pack) are fatal: the original record is
 * not written mixed with re-packed output.
 *
 * miniSEED 2 sequence numbers are rewritten per SourceID in write
 * (time) order, starting at 1 and wrapping at 1000000.
 ***************************************************************************/

#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libmseed.h>

#include "local.h"

static int outputreclen = 0; /* 0 = keep original record length */
static int wrote_this_pack = 0;
static uint64_t *totalrecsoutp = NULL;
static uint64_t *totalbytesoutp = NULL;

/* Per-SourceID miniSEED 2 sequence, assigned in write (time) order from 1. */
typedef struct SidSeq_s
{
  char *sid;
  int64_t next;
  struct SidSeq_s *nextsid;
} SidSeq;

static SidSeq *sidseqs = NULL;

static void
local_seq_reset (void)
{
  SidSeq *p;

  while (sidseqs)
  {
    p = sidseqs;
    sidseqs = p->nextsid;
    free (p->sid);
    free (p);
  }
}

static int64_t
local_take_v2seq (const char *sid)
{
  SidSeq *p;
  const char *key = (sid && sid[0]) ? sid : "";

  for (p = sidseqs; p; p = p->nextsid)
  {
    if (strcmp (p->sid, key) == 0)
    {
      int64_t seq = p->next;
      p->next = (p->next + 1) % 1000000;
      return seq;
    }
  }

  p = (SidSeq *)malloc (sizeof (SidSeq));
  if (!p)
    return -1;

  p->sid = (char *)malloc (strlen (key) + 1);
  if (!p->sid)
  {
    free (p);
    return -1;
  }
  memcpy (p->sid, key, strlen (key) + 1);

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

static void
local_pack_reset (void)
{
  if (packmsr)
    msr3_free (&packmsr);
  packcap = 0;
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

int
local_pack_flush (void (*handler) (char *, int, void *), void *handlerdata,
                  MS3Record **msrslot, int8_t verbose)
{
  int rv;

  if (!packmsr)
    return 0;

  if (packmsr->numsamples > 0)
  {
    rv = local_pack_commit (handler, handlerdata, msrslot, MSF_FLUSHDATA, verbose);
    if (rv)
      return -1;

    if (packmsr && packmsr->numsamples > 0)
    {
      ms_log (2, "Error packing remaining samples for %s\n", packmsr->sid);
      local_pack_reset ();
      return -1;
    }
  }

  local_pack_reset ();
  return 0;
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
                         const char *sid)
{
  char seqstr[7];
  int64_t seq;

  if (outputreclen <= 0 || formatversion != 2 || reclen < 6 || !record)
    return;

  seq = local_take_v2seq (sid);
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
