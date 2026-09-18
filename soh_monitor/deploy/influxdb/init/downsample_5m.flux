option task = {name: "soh downsample 5m", every: 5m, offset: 1m}

// 원본 180일 만료 뒤에도 5분 집계로 2년 추세를 본다.
// 제조사 전용(vendor) 도 recorder_vendor_metric 이라 같이 내려간다. 공통 화면은 쓰지 않는다.
from(bucket: "soh")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement =~ /^recorder_/)
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> to(bucket: "soh_5m", org: "observatory")
