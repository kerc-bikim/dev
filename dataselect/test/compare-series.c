/***************************************************************************
 * Compare two miniSEED files as time-series: sample times and values
 * must match exactly.  Record/block framing may differ.
 *
 * Exit 0 if identical, 1 if they differ, 2 on usage/read error.
 ***************************************************************************/

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libmseed.h>

static int load_traces (const char *path, MS3TraceList **ppmstl);
static int compare_lists (const MS3TraceList *a, const MS3TraceList *b);
static int compare_segments (const char *sid, const MS3TraceSeg *a, const MS3TraceSeg *b);
static size_t sample_bytes (char sampletype, int64_t numsamples);

int
main (int argc, char **argv)
{
  MS3TraceList *lista = NULL;
  MS3TraceList *listb = NULL;
  int rv;

  if (argc != 3)
  {
    fprintf (stderr, "Usage: %s fileA fileB\n", argv[0]);
    return 2;
  }

  ms_loginit (NULL, NULL, NULL, "ERROR: ");

  if (load_traces (argv[1], &lista) || load_traces (argv[2], &listb))
  {
    mstl3_free (&lista, 1);
    mstl3_free (&listb, 1);
    return 2;
  }

  rv = compare_lists (lista, listb);

  mstl3_free (&lista, 1);
  mstl3_free (&listb, 1);

  return rv;
}

static int
load_traces (const char *path, MS3TraceList **ppmstl)
{
  uint32_t flags = MSF_UNPACKDATA | MSF_VALIDATECRC;
  int retcode;

  retcode = ms3_readtracelist (ppmstl, path, NULL, 1, flags, 0);
  if (retcode != MS_NOERROR)
  {
    fprintf (stderr, "Cannot read %s: %s\n", path, ms_errorstr (retcode));
    return -1;
  }

  return 0;
}

static int
compare_lists (const MS3TraceList *a, const MS3TraceList *b)
{
  const MS3TraceID *ida;
  const MS3TraceID *idb;
  const MS3TraceSeg *sega;
  const MS3TraceSeg *segb;
  uint32_t segi;

  if (a->numtraceids != b->numtraceids)
  {
    fprintf (stderr, "Trace ID count differs: %" PRIu32 " vs %" PRIu32 "\n",
             a->numtraceids, b->numtraceids);
    return 1;
  }

  ida = a->traces.next[0];
  idb = b->traces.next[0];

  while (ida && idb)
  {
    if (strcmp (ida->sid, idb->sid) != 0)
    {
      fprintf (stderr, "SourceID differs: %s vs %s\n", ida->sid, idb->sid);
      return 1;
    }

    if (ida->pubversion != idb->pubversion)
    {
      fprintf (stderr, "%s: pubversion differs: %u vs %u\n",
               ida->sid, ida->pubversion, idb->pubversion);
      return 1;
    }

    if (ida->numsegments != idb->numsegments)
    {
      fprintf (stderr, "%s: segment count differs: %" PRIu32 " vs %" PRIu32 "\n",
               ida->sid, ida->numsegments, idb->numsegments);
      return 1;
    }

    sega = ida->first;
    segb = idb->first;
    segi = 0;
    while (sega && segb)
    {
      if (compare_segments (ida->sid, sega, segb))
      {
        fprintf (stderr, "%s: mismatch in segment %" PRIu32 "\n", ida->sid, segi);
        return 1;
      }
      sega = sega->next;
      segb = segb->next;
      segi++;
    }

    if (sega || segb)
    {
      fprintf (stderr, "%s: segment lists are not the same length\n", ida->sid);
      return 1;
    }

    ida = ida->next[0];
    idb = idb->next[0];
  }

  if (ida || idb)
  {
    fprintf (stderr, "Trace ID lists are not the same length\n");
    return 1;
  }

  return 0;
}

static int
compare_segments (const char *sid, const MS3TraceSeg *a, const MS3TraceSeg *b)
{
  char atime[40] = {0};
  char btime[40] = {0};
  size_t nbytes;
  int64_t i;

  if (a->starttime != b->starttime)
  {
    ms_nstime2timestr_n (a->starttime, atime, sizeof (atime), ISOMONTHDAY_Z, NANO);
    ms_nstime2timestr_n (b->starttime, btime, sizeof (btime), ISOMONTHDAY_Z, NANO);
    fprintf (stderr, "%s: start time differs: %s vs %s\n", sid, atime, btime);
    return 1;
  }

  if (a->endtime != b->endtime)
  {
    ms_nstime2timestr_n (a->endtime, atime, sizeof (atime), ISOMONTHDAY_Z, NANO);
    ms_nstime2timestr_n (b->endtime, btime, sizeof (btime), ISOMONTHDAY_Z, NANO);
    fprintf (stderr, "%s: end time differs: %s vs %s\n", sid, atime, btime);
    return 1;
  }

  if (a->samprate != b->samprate)
  {
    fprintf (stderr, "%s: sample rate differs: %.12f vs %.12f\n", sid, a->samprate, b->samprate);
    return 1;
  }

  if (a->samplecnt != b->samplecnt || a->numsamples != b->numsamples)
  {
    fprintf (stderr, "%s: sample count differs: %" PRId64 "/%" PRId64 " vs %" PRId64 "/%" PRId64 "\n",
             sid, a->samplecnt, a->numsamples, b->samplecnt, b->numsamples);
    return 1;
  }

  if (a->sampletype != b->sampletype)
  {
    fprintf (stderr, "%s: sample type differs: '%c' vs '%c'\n", sid, a->sampletype, b->sampletype);
    return 1;
  }

  if (a->numsamples == 0)
    return 0;

  if (!a->datasamples || !b->datasamples)
  {
    fprintf (stderr, "%s: missing unpacked samples\n", sid);
    return 1;
  }

  nbytes = sample_bytes (a->sampletype, a->numsamples);
  if (nbytes == 0)
  {
    fprintf (stderr, "%s: unknown sample type '%c'\n", sid, a->sampletype);
    return 1;
  }

  if (memcmp (a->datasamples, b->datasamples, nbytes) == 0)
    return 0;

  /* Report the first mismatched sample */
  if (a->sampletype == 'i')
  {
    const int32_t *ia = a->datasamples;
    const int32_t *ib = b->datasamples;
    for (i = 0; i < a->numsamples; i++)
    {
      if (ia[i] != ib[i])
      {
        fprintf (stderr, "%s: sample %" PRId64 " differs: %d vs %d\n", sid, i, ia[i], ib[i]);
        return 1;
      }
    }
  }
  else if (a->sampletype == 'f')
  {
    const float *fa = a->datasamples;
    const float *fb = b->datasamples;
    for (i = 0; i < a->numsamples; i++)
    {
      if (fa[i] != fb[i])
      {
        fprintf (stderr, "%s: sample %" PRId64 " differs: %.9g vs %.9g\n", sid, i, fa[i], fb[i]);
        return 1;
      }
    }
  }
  else if (a->sampletype == 'd')
  {
    const double *da = a->datasamples;
    const double *db = b->datasamples;
    for (i = 0; i < a->numsamples; i++)
    {
      if (da[i] != db[i])
      {
        fprintf (stderr, "%s: sample %" PRId64 " differs: %.17g vs %.17g\n", sid, i, da[i], db[i]);
        return 1;
      }
    }
  }
  else
  {
    fprintf (stderr, "%s: sample payload differs (%zu bytes)\n", sid, nbytes);
  }

  return 1;
}

static size_t
sample_bytes (char sampletype, int64_t numsamples)
{
  size_t width = ms_samplesize (sampletype);

  if (width == 0 || numsamples < 0)
    return 0;

  return width * (size_t)numsamples;
}
