.PHONY: smoke test
export PYTHONPATH := .
test:
	@python3 -m unittest tests.test_rrm tests.test_mqtt_status -v
smoke: test
	@PYTHONPATH=. python3 examples/fleet_e2e.py
	@PYTHONPATH=. python3 examples/mqtt_sense_loop.py
	@PYTHONPATH=. python3 examples/plant_status_demo.py
	@PYTHONPATH=. python3 -m aspen_edge.status_cli --demo; test $$? -eq 1
	@echo aspen-edge-rrm smoke ok
