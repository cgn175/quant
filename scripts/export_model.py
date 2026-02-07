#!/usr/bin/env python3
"""Export XGBoost model to ONNX format for Go inference."""

import argparse
from pathlib import Path

import numpy as np
import xgboost as xgb
import onnx
from onnxmltools.convert import convert_xgboost
from onnxconverter_common import FloatTensorType
import joblib
import json


def export_to_onnx(
    model_path: Path,
    features_path: Path,
    output_path: Path,
):
    """Convert XGBoost model to ONNX format."""
    
    print(f"Loading model from {model_path}")
    
    if model_path.suffix == ".joblib":
        model = joblib.load(model_path)
    else:
        model = xgb.XGBClassifier()
        model.load_model(model_path)
    
    with open(features_path) as f:
        features = json.load(f)
    
    n_features = len(features)
    print(f"Number of features: {n_features}")
    
    initial_type = [("float_input", FloatTensorType([None, n_features]))]
    
    print("Converting to ONNX...")
    onnx_model = convert_xgboost(
        model,
        initial_types=initial_type,
        target_opset=12,
    )
    
    for output in onnx_model.graph.output:
        if "probabilities" in output.name.lower() or output.name == "output_probability":
            output.name = "probabilities"
        elif "label" in output.name.lower():
            output.name = "label"
    
    for node in onnx_model.graph.node:
        for i, out in enumerate(node.output):
            if "probabilities" in out.lower() or out == "output_probability":
                node.output[i] = "probabilities"
    
    onnx.save_model(onnx_model, str(output_path))
    print(f"Saved ONNX model to {output_path}")
    
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
