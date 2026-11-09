"""Phase 11 evaluation command-line tools (run from backend/):

    python -m eval.validate --set golden_v1 [--lecture-id <uuid>]
    python -m eval.segments --lecture-id <uuid>
    python -m eval.run --set golden_v1 --lecture-id <uuid> --generator cloud|finetuned|base|all
    python -m eval.import_offline

The logic lives in app/services/evaluation/; these files only parse arguments and print.
"""
