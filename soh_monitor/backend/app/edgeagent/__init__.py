"""지역 Edge Collector.

중앙 Collector 와 같은 Adapter 로 기록계를 수집한다. 결과는 로컬 Spool 에 먼저
남기고, 중앙이 살아 있을 때만 올린다. 중앙이 꺼져 있어도 수집은 멈추지 않는다.
"""

AGENT_VERSION = "0.7.0"
