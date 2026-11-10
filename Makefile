# Independent validation of Consumer PD Model v1.0
PY ?= python

.PHONY: all data model validate report test zip clean

all: data model validate test report

data:  ## regenerate the synthetic portfolio (deterministic seed)
	$(PY) data/make_data.py

model: ## first line: fit and freeze the production model
	$(PY) model/develop_model.py > /dev/null

validate: ## second line: run every validation test, write outputs/
	$(PY) -m validation.run_validation

test: ## unit tests for the statistical helpers
	$(PY) -m pytest tests -q

report: ## build report markdown from outputs/, then DOCX and PDF
	$(PY) report/build_report.py

zip: ## package the project
	cd .. && rm -f credit-model-validation.zip && zip -qr credit-model-validation.zip credit-model-validation -x '*/__pycache__/*' '*/.pytest_cache/*' 'credit-model-validation/report/_build/*'

clean:
	rm -rf outputs report/validation_report.* report/_build
