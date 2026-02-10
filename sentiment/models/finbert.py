from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from functools import lru_cache
from config import get_settings

PROSUS_LABELS = {0: "positive", 1: "negative", 2: "neutral"}
CRYPTO_LABELS = {0: "negative", 1: "neutral", 2: "positive"}

RISK_KEYWORDS = [
    "regulatory", "crackdown", "lawsuit", "ban", "investigation", "halted",
    "exploit", "hack", "hacked", "stolen", "scam", "fraud", "rug pull",
    "rugpull", "unusable", "insanely high", "fees are", "shutdown",
    "arrested", "charged", "indicted", "sanctioned", "delisted",
    "insolvent", "bankrupt", "collapse", "liquidat",
]


class FinBERTAnalyzer:
    def __init__(self):
        settings = get_settings()
        self.prosus_model_name = "ProsusAI/finbert"
        self.crypto_model_name = "burakutf/finetuned-finbert-crypto"

        self.prosus_tokenizer = AutoTokenizer.from_pretrained(self.prosus_model_name)
        self.prosus_model = AutoModelForSequenceClassification.from_pretrained(self.prosus_model_name)
        self.prosus_model.eval()

        self.crypto_tokenizer = AutoTokenizer.from_pretrained(self.crypto_model_name)
        self.crypto_model = AutoModelForSequenceClassification.from_pretrained(self.crypto_model_name)
        self.crypto_model.eval()

        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        self.prosus_model.to(self.device)
        self.crypto_model.to(self.device)

    def _run_model(self, model, tokenizer, texts, label_map, max_length):
        results = []
        batch_size = 16

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = model(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)

            for prob in probs:
                results.append(
                    {
                        label_map[0]: prob[0].item(),
                        label_map[1]: prob[1].item(),
                        label_map[2]: prob[2].item(),
                    }
                )

        return results

    def _has_risk_keywords(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in RISK_KEYWORDS)

    def _resolve_ensemble(self, prosus: dict, crypto: dict, text: str) -> dict:
        neg_threshold = 0.55

        if prosus["negative"] >= neg_threshold or crypto["negative"] >= neg_threshold:
            return prosus if prosus["negative"] >= crypto["negative"] else crypto

        if self._has_risk_keywords(text):
            combined_neg = max(prosus["negative"], crypto["negative"])
            combined_neu = max(prosus["neutral"], crypto["neutral"])
            if combined_neg > 0.3:
                return {
                    "positive": min(prosus["positive"], crypto["positive"]),
                    "negative": combined_neg,
                    "neutral": combined_neu,
                }

        if prosus["positive"] > 0.5 and crypto["positive"] > 0.5:
            return crypto

        return {
            "positive": (prosus["positive"] + crypto["positive"]) / 2,
            "negative": (prosus["negative"] + crypto["negative"]) / 2,
            "neutral": (prosus["neutral"] + crypto["neutral"]) / 2,
        }

    def analyze(self, texts: list[str]) -> list[dict]:
        if not texts:
            return []

        prosus_results = self._run_model(
            self.prosus_model, self.prosus_tokenizer, texts, PROSUS_LABELS, 512
        )
        crypto_results = self._run_model(
            self.crypto_model, self.crypto_tokenizer, texts, CRYPTO_LABELS, 128
        )

        results = []
        for text, prosus, crypto in zip(texts, prosus_results, crypto_results):
            resolved = self._resolve_ensemble(prosus, crypto, text)
            results.append(resolved)

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
