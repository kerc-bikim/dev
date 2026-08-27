# Earthworm Linux environment — edited by Earthworm Web Control
export EW_HOME=/opt/earthworm
export EW_VERSION=earthworm_8.0
export EW_RUN_DIR=/opt/earthworm/run_working
export EW_PARAMS="${EW_RUN_DIR}/params/"
export EW_LOG="${EW_RUN_DIR}/log/"
export EW_DATA_DIR="${EW_RUN_DIR}/data/"
export EW_INSTALLATION=INST_UNKNOWN
export SYS_NAME=$(hostname)
export PATH="${EW_HOME}/${EW_VERSION}/bin:${PATH}"
