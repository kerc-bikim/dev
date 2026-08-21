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
 * miniSEED 2 sequence numbers are rewritten per output file and
 * SourceID in write (time) order, starting at 1 and wrapping at
 * 1000000.  A new archive file (for example a new SDS day) starts
 * again at 1.
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

/* Samples buffered across input records until a -B record fills. */
static MS3Record *packmsr = NULL;
static size_t packcap = 0;

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
  local_pack_reset ();
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

static int
local_same_pack_stream (const MS3Record *a, const MS3Record *b)
{
  double ratio;

  if (!a || !b)
    return 0;

  if (strcmp (a->sid, b->sid) != 0)
    return 0;
  if (a->formatversion != b->formatversion)
    return 0;
  if (a->pubversion != b->pubversion)
    return 0;
  if (a->encoding != b->encoding)
    return 0;
  if (a->sampletype != b->sampletype)
    return 0;
  if (a->samprate <= 0.0 || b->samprate <= 0.0)
    return 0;

  ratio = b->samprate / a->samprate;
  if (ratio < 0.999 || ratio > 1.001)
    return 0;

  return 1;
}

static int
local_pack_start (MS3Record *msr)
{
  packmsr = msr3_duplicate (msr, 1);
  if (!packmsr)
  {
    ms_log (2, "Cannot buffer miniSEED record for packing\n");
    return -1;
  }

  /* Avoid sharing the input record buffer with later packing. */
  packmsr->record = NULL;
  if (outputreclen > 0)
    packmsr->reclen = outputreclen;

  packcap = packmsr->datasize;
  return 0;
}

static int
local_pack_append (MS3Record *src)
{
  uint8_t samplesize;
  size_t addbytes;
  size_t need;
  size_t newcap;
  void *resized;

  if (!packmsr || !src || src->numsamples <= 0 || !src->datasamples)
    return -1;

  samplesize = ms_samplesize (src->sampletype);
  if (!samplesize)
  {
    ms_log (2, "Unknown sample type '%c' for %s\n", src->sampletype, src->sid);
    return -1;
  }

  addbytes = (size_t)samplesize * (size_t)src->numsamples;
  need = (size_t)samplesize * (size_t)(packmsr->numsamples + src->numsamples);

  if (need > packcap)
  {
    newcap = packcap ? packcap : need;
    while (newcap < need)
    {
      if (newcap > SIZE_MAX / 2)
      {
        newcap = need;
        break;
      }
      newcap *= 2;
    }

    resized = libmseed_memory.realloc (packmsr->datasamples, newcap);
    if (!resized)
    {
      ms_log (2, "Cannot grow sample buffer for %s\n", src->sid);
      return -1;
    }

    packmsr->datasamples = resized;
    packcap = newcap;
  }

  memcpy ((uint8_t *)packmsr->datasamples + ((size_t)samplesize * (size_t)packmsr->numsamples),
          src->datasamples, addbytes);

  packmsr->numsamples += src->numsamples;
  packmsr->samplecnt = packmsr->numsamples;
  packmsr->datasize = need;

  return 0;
}

static int
local_pack_commit (void (*handler) (char *, int, void *), void *handlerdata,
                   MS3Record **msrslot, uint32_t flags, int8_t verbose)
{
  int packedrecords;
  int64_t packedsamples = 0;
  int64_t remaining;
  uint8_t samplesize;
  nstime_t nexttime;

  if (!packmsr || packmsr->numsamples <= 0)
    return 0;

  samplesize = ms_samplesize (packmsr->sampletype);
  if (!samplesize)
  {
    ms_log (2, "Unknown sample type '%c' for %s\n", packmsr->sampletype, packmsr->sid);
    return -1;
  }

  if (msrslot)
    *msrslot = packmsr;

  packedrecords = msr3_pack (packmsr, handler, handlerdata, &packedsamples, flags, verbose);

  if (packedrecords < 0)
  {
    ms_log (2, "Error packing miniSEED record for %s\n", packmsr->sid);
    local_pack_reset ();
    return -1;
  }

  if (packedsamples <= 0)
    return 0;

  nexttime = ms_sampletime (packmsr->starttime, packedsamples, packmsr->samprate);
  if (nexttime == NSTERROR)
  {
    ms_log (2, "Cannot advance start time after packing %s\n", packmsr->sid);
    local_pack_reset ();
    return -1;
  }

  remaining = packmsr->numsamples - packedsamples;
  if (remaining < 0)
    remaining = 0;

  if (remaining > 0)
  {
    memmove (packmsr->datasamples,
             (uint8_t *)packmsr->datasamples + ((size_t)samplesize * (size_t)packedsamples),
             (size_t)samplesize * (size_t)remaining);
  }

  packmsr->starttime = nexttime;
  packmsr->numsamples = remaining;
  packmsr->samplecnt = remaining;
  packmsr->datasize = (size_t)samplesize * (size_t)remaining;

  return 0;
}

int
local_pack_feed (MS3Record *msr, nstime_t nstimetol,
                 void (*handler) (char *, int, void *), void *handlerdata,
                 MS3Record **msrslot, int8_t verbose)
{
  nstime_t expected;
  nstime_t delta;
  int newstream = 0;

  if (!msr)
    return -1;

  if (msr->numsamples <= 0)
    return 0;

  if (!packmsr)
  {
    if (local_pack_start (msr))
      return -1;
  }
  else
  {
    if (!local_same_pack_stream (packmsr, msr))
    {
      newstream = 1;
    }
    else
    {
      expected = ms_sampletime (packmsr->starttime, packmsr->numsamples, packmsr->samprate);
      if (expected == NSTERROR)
      {
        ms_log (2, "Cannot determine next sample time for %s\n", packmsr->sid);
        local_pack_reset ();
        return -1;
      }

      if (msr->starttime > expected)
        delta = msr->starttime - expected;
      else
        delta = expected - msr->starttime;

      if (nstimetol < 0)
        nstimetol = 0;

      if (delta > nstimetol)
        newstream = 1;
    }

    if (newstream)
    {
      if (local_pack_flush (handler, handlerdata, msrslot, verbose))
        return -1;

      if (local_pack_start (msr))
        return -1;
    }
    else if (local_pack_append (msr))
    {
      local_pack_reset ();
      return -1;
    }
  }

  return local_pack_commit (handler, handlerdata, msrslot, 0, verbose);
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
