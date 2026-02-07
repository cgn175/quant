from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from functools import lru_cache
from config import get_settings


class FinBERTAnalyzer:
    def __init__(self):
        settings = get_settings()
        self.tokenizer = AutoTokenizer.from_pretrained(settings.model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(settings.model_name)
        self.model.eval()
        
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")
        
        self.model.to(self.device)

    def analyze(self, texts: list[str]) -> list[dict]:
        if not texts:
            return []

        results = []
        batch_size = 16

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)

            for prob in probs:
                results.append(
                    {
                        "positive": prob[0].item(),
                        "negative": prob[1].item(),
                        "neutral": prob[2].item(),
                    }
                )

        return results

    def compute_score(self, sentiments: list[dict], weights: list[float] = None) -> float:
        if not sentiments:
            return 0.0

        if weights is None:
            weights = [1.0] * len(sentiments)

        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0

        weighted_score = 0.0
        for sent, weight in zip(sentiments, weights):
            score = sent["positive"] - sent["negative"]
            weighted_score += score * weight

        return weighted_score / total_weight


@lru_cache
def get_analyzer() -> FinBERTAnalyzer:
    return FinBERTAnalyzer()
