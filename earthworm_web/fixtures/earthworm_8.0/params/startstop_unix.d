#
# startstop_unix.d — first Ring receives status/pau/stopmodule traffic
#
Ring   STATUS_RING  128
Ring   WAVE_RING    1024
Ring   PICK_RING    1024
Ring   HYPO_RING    1024

nMessageQueue  100
KillDelay      10
HardKillDelay  5
maxStatusLineLen  80

Process          "statmgr statmgr.d"
 Class/Priority    OTHER 0

# Process          "pick_ew pick_ew.d"
#  Class/Priority    OTHER 0

# Process          "binder_ew binder_ew.d"
#  Class/Priority    OTHER 0

# Process          "eqproc eqproc.d"
#  Class/Priority    OTHER 0

# Process          "slink2ew slink2ew.d"
#  Class/Priority    OTHER 0

# Process          "q3302ew q3302ew.d"
#  Class/Priority    OTHER 0

# Process          "tankplayer tankplayer.d"
#  Class/Priority    OTHER 0
