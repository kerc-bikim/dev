export function responsePngFilename(
  output: string,
  series: { nslc: string }[]
): string {
  const unit = output || "VEL";
  if (series.length <= 1) {
    const nslc = series[0]?.nslc || "channel";
    return `${nslc}_${unit}_response.png`;
  }
  return `response_compare_${series.length}ch_${unit}.png`;
}
