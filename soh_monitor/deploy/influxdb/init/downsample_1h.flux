option task = {name: "soh downsample 1h", every: 1h, offset: 5m}

from(bucket: "soh_5m")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement =~ /^recorder_/)
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> to(bucket: "soh_1h", org: "observatory")
