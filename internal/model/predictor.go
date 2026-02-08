package model

import (
	"fmt"
	"sync"

	ort "github.com/yalue/onnxruntime_go"
)

const (
	ClassDown    = 0
	ClassNeutral = 1
	ClassUp      = 2
)

type Prediction struct {
	ProbDown    float64
	ProbNeutral float64
	ProbUp      float64
}

func (p *Prediction) ArgMax() int {
	if p.ProbDown >= p.ProbNeutral && p.ProbDown >= p.ProbUp {
		return ClassDown
	}
	if p.ProbUp >= p.ProbNeutral {
		return ClassUp
	}
	return ClassNeutral
}

type Predictor struct {
	session      *ort.AdvancedSession
	inputTensor  *ort.Tensor[float32]
	outputTensor *ort.Tensor[float32]
	numFeatures  int64
	numClasses   int
	mu           sync.Mutex
}

// NewPredictor creates a predictor with the specified output class count.
// Use numClasses=3 for multi-class (DOWN/NEUTRAL/UP) models.
// Use numClasses=2 for binary (DOWN/UP) models.
func NewPredictor(modelPath string, numFeatures int, numClasses int) (*Predictor, error) {
	if numClasses < 2 || numClasses > 3 {
		return nil, fmt.Errorf("numClasses must be 2 or 3, got %d", numClasses)
	}

	inputShape := ort.NewShape(1, int64(numFeatures))
	inputTensor, err := ort.NewEmptyTensor[float32](inputShape)
	if err != nil {
		return nil, fmt.Errorf("failed to create input tensor: %w", err)
	}

	outputShape := ort.NewShape(1, int64(numClasses))
	outputTensor, err := ort.NewEmptyTensor[float32](outputShape)
	if err != nil {
		inputTensor.Destroy()
		return nil, fmt.Errorf("failed to create output tensor: %w", err)
	}

	session, err := ort.NewAdvancedSession(
		modelPath,
		[]string{"float_input"},
		[]string{"probabilities"},
		[]ort.Value{inputTensor},
		[]ort.Value{outputTensor},
		nil,
	)
	if err != nil {
		inputTensor.Destroy()
		outputTensor.Destroy()
		return nil, fmt.Errorf("failed to create session: %w", err)
	}

	return &Predictor{
		session:      session,
		inputTensor:  inputTensor,
		outputTensor: outputTensor,
		numFeatures:  int64(numFeatures),
		numClasses:   numClasses,
	}, nil
}

func (p *Predictor) Predict(features []float64) (*Prediction, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if int64(len(features)) != p.numFeatures {
		return nil, fmt.Errorf("expected %d features, got %d", p.numFeatures, len(features))
	}

	inputData := p.inputTensor.GetData()
	for i, f := range features {
		inputData[i] = float32(f)
	}

	if err := p.session.Run(); err != nil {
		return nil, fmt.Errorf("inference failed: %w", err)
	}

	outputData := p.outputTensor.GetData()
	if len(outputData) < p.numClasses {
		return nil, fmt.Errorf("unexpected output size: %d (expected %d)", len(outputData), p.numClasses)
	}

	if p.numClasses == 2 {
		// Binary model: output is [P(DOWN), P(UP)]
		// Map to Prediction with ProbNeutral=0 so that:
		//   - isValidPrediction() sum check passes (ProbDown + 0 + ProbUp ≈ 1.0)
		//   - ArgMax() works correctly (ProbNeutral=0 can never win)
		return &Prediction{
			ProbDown:    float64(outputData[0]),
			ProbNeutral: 0,
			ProbUp:      float64(outputData[1]),
		}, nil
	}

	// 3-class model: output is [P(DOWN), P(NEUTRAL), P(UP)]
	return &Prediction{
		ProbDown:    float64(outputData[0]),
		ProbNeutral: float64(outputData[1]),
		ProbUp:      float64(outputData[2]),
	}, nil
}

func (p *Predictor) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	var errs []error

	if p.session != nil {
		if err := p.session.Destroy(); err != nil {
			errs = append(errs, fmt.Errorf("session destroy failed: %w", err))
		}
		p.session = nil
	}

	if p.inputTensor != nil {
		if err := p.inputTensor.Destroy(); err != nil {
			errs = append(errs, fmt.Errorf("input tensor destroy failed: %w", err))
		}
		p.inputTensor = nil
	}

	if p.outputTensor != nil {
		if err := p.outputTensor.Destroy(); err != nil {
			errs = append(errs, fmt.Errorf("output tensor destroy failed: %w", err))
		}
		p.outputTensor = nil
	}

	if len(errs) > 0 {
		return fmt.Errorf("cleanup errors: %v", errs)
	}
	return nil
}
