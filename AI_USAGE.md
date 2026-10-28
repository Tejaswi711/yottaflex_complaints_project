# AI Usage Disclosure

## Where AI Accelerated the Work

AI tools were used during development to clarify project requirements, explore implementation approaches, understand business rules, and review technical concepts.

AI assistance contributed to the initial implementation of the data generator, business-rule modules, schema definitions, validation and evaluation scripts, reproducibility checks, and project documentation.

## Where I Relied on AI

I relied on AI tools substantially for the initial project structure and implementation of the scripts. They also provided guidance on technical concepts, business rules, troubleshooting, and validation approaches.

## My Development Work

My work included running and testing the complaint management synthetic data generation project. This involved:

- Running the Python scripts and examining the generated CSV datasets and output files.
- Executing validation and evaluation scripts to check data integrity, business rules, anomaly detection, and evaluation metrics.
- Running reproducibility checks to compare row counts and SHA-256 checksums across runs.
- Examining the reported results, assumptions, and limitations documented in the project.

## Testing and Validation

The validation script reported a passing result, the evaluation script produced the documented metrics, and the reproducibility check reported matching row counts and checksums across runs.

## Known Limitations

The project's assumptions and limitations are documented in `README.md`. These include the keyword-based complaint classifier, the use of a single SLA clock per complaint, and the handling of reopened complaints.

