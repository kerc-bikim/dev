# Build environment can be configured with the following
# variables, set in the environment or on the command line,
# e.g. make CFLAGS="-g -Wall":
#   CC : Specify the C compiler to use
#   CFLAGS : Specify compiler options to use (default: -O2)
#   LDFLAGS : Specify linker options to use
#   WITHOUTURL : Set to any value to disable URL support via libcurl

# Recommended default optimization level (overridable on command line)
CFLAGS ?= -O2

# Automatically configure URL support if libcurl is present
# Test for curl-config command and add build options if found
# Prefer /usr/bin/curl-config over any other curl-config
ifndef WITHOUTURL
  ifneq (,$(wildcard /usr/bin/curl-config))
     CURL_CONFIG := /usr/bin/curl-config
  else ifneq (,$(shell command -v curl-config))
     CURL_CONFIG := $(shell command -v curl-config)
  endif
endif

ifneq (,$(CURL_CONFIG))
  export LM_CURL_VERSION=$(shell $(CURL_CONFIG) --version)
  EXTRA_CFLAGS := -DLIBMSEED_URL
  EXTRA_LDFLAGS := $(shell $(CURL_CONFIG) --libs)
  $(info Configured with $(LM_CURL_VERSION))
endif

# Variables passed to sub-makes
SUBMAKE_ARGS = CFLAGS="$(CFLAGS) $(EXTRA_CFLAGS)" LDFLAGS="$(LDFLAGS) $(EXTRA_LDFLAGS)"

.PHONY: all
all:
	$(MAKE) -C libmseed all $(SUBMAKE_ARGS)
	$(MAKE) -C src all $(SUBMAKE_ARGS)

.PHONY: clean
clean:
	$(MAKE) -C libmseed clean $(SUBMAKE_ARGS)
	$(MAKE) -C src clean $(SUBMAKE_ARGS)
	rm -f test/compare-series

.PHONY: test
test: all test/compare-series
	@test/run-tests.py

test/compare-series: test/compare-series.c libmseed/libmseed.a
	$(CC) $(CFLAGS) $(EXTRA_CFLAGS) -Ilibmseed -o $@ $< -Llibmseed -lmseed $(EXTRA_LDFLAGS) $(LDFLAGS)

.PHONY: install
install:
	@echo
	@echo "No install method"
	@echo "Copy the binary and documentation to desired location"
	@echo
