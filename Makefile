.PHONY: smoke test
export PYTHONPATH := .
test:
	@python3 -m unittest tests.test_rrm -v
smoke: test
	@PYTHONPATH=. python3 examples/fleet_e2e.py
	@echo aspen-edge-rrm smoke ok
