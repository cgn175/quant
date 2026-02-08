#!/usr/bin/env python3
"""Export XGBoost model to ONNX format for Go inference."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import onnx
import xgboost as xgb
from onnxconverter_common import FloatTensorType
from onnxmltools.convert import convert_xgboost


def export_to_onnx(
    model_path: Path,
    features_path: Path,
    output_path: Path,
):
    """Convert XGBoost model to ONNX format.

    NOTE: onnxmltools requires feature names to follow the pattern 'f%d'.
    If the trained model was fit with named features (e.g. 'ema_5'), conversion
    will fail. To avoid that we map feature names to 'f0'..'f{n-1}' and set the
    underlying booster feature names before conversion.
    """
    print(f"Loading model from {model_path}")

    # Load model (joblib or raw XGBoost JSON)
    if model_path.suffix == ".joblib":
        model = joblib.load(model_path)
    else:
        model = xgb.XGBClassifier()
        model.load_model(model_path)

    # Load feature names from features.json (a list of feature names)
    with open(features_path) as f:
        features = json.load(f)

    n_features = len(features)
    print(f"Number of features: {n_features}")

    # Create safe feature names required by onnxmltools ('f0', 'f1', ...)
    safe_feature_names = [f"f{i}" for i in range(n_features)]
    print("Mapping original feature names to safe feature names (f0..fN)")

    # Attempt to set feature names on the underlying booster so the converter
    # sees the safe names. The model may be a scikit-learn wrapper (XGBClassifier)
    # or a raw Booster. Handle both cases.
    try:
        # If model is sklearn wrapper
        booster = model.get_booster()
        booster.feature_names = safe_feature_names
        # Also set feature_names on the sklearn wrapper if attribute exists
        try:
            model.feature_names_in_ = safe_feature_names  # type: ignore
        except Exception:
            # not critical
            pass
        print("Set feature names on sklearn wrapper booster.")
    except Exception:
        try:
            # If model is a raw Booster
            model.feature_names = safe_feature_names  # type: ignore
            print("Set feature names on raw booster.")
        except Exception as e:
            print(f"Warning: unable to set booster feature names: {e}")

    # Build initial_type using the same input name the Go runtime expects.
    initial_type = [("float_input", FloatTensorType([None, n_features]))]

    print("Converting to ONNX...")
    # Convert using onnxmltools; the booster now uses f0..fN names which the
    # converter will accept.
    onnx_model = convert_xgboost(
        model,
        initial_types=initial_type,
        target_opset=12,
    )

    # Normalize output names to expected names
    for output in onnx_model.graph.output:
        if (
            "probabilities" in output.name.lower()
            or output.name == "output_probability"
        ):
            output.name = "probabilities"
        elif "label" in output.name.lower():
            output.name = "label"

    for node in onnx_model.graph.node:
        for i, out in enumerate(node.output):
            if "probabilities" in out.lower() or out == "output_probability":
                node.output[i] = "probabilities"

    # Save model
    onnx.save_model(onnx_model, str(output_path))
    print(f"Saved ONNX model to {output_path}")

    # Verify model
    print("\nVerifying ONNX model...")
    onnx_model = onnx.load(str(output_path))
    onnx.checker.check_model(onnx_model)
    print("ONNX model is valid!")

    print("\nModel inputs:")
    for inp in onnx_model.graph.input:
        print(f"  - {inp.name}")
    print("Model outputs:")
    for out in onnx_model.graph.output:
        print(f"  - {out.name}")

    # Test inference with onnxruntime
    print("\nTesting inference...")
    import onnxruntime as ort

    session = ort.InferenceSession(str(output_path))
    input_name = session.get_inputs()[0].name

    test_input = np.random.randn(1, n_features).astype(np.float32)
    outputs = session.run(None, {input_name: test_input})

    print(f"Input shape: {test_input.shape}")
    print(f"Output (labels): {outputs[0]}")
    print(f"Output (probabilities): {outputs[1]}")


def main():
    parser = argparse.ArgumentParser(description="Export model to ONNX")
    parser.add_argument(
        "--model",
        type=str,
        default="models/xgboost_model.joblib",
        help="Input model path",
    )
    parser.add_argument(
        "--features",
        type=str,
        default="models/features.json",
        help="Features JSON path",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models/xgboost_model.onnx",
        help="Output ONNX path",
    )

    args = parser.parse_args()

    export_to_onnx(
        Path(args.model),
        Path(args.features),
        Path(args.output),
    )


if __name__ == "__main__":
    main()
