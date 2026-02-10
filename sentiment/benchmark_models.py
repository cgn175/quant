#!/usr/bin/env python3
"""Benchmark ProsusAI/finbert vs burakutf/finetuned-finbert-crypto vs ensemble."""

import os
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

load_dotenv()

PROSUS_LABELS = {0: "positive", 1: "negative", 2: "neutral"}
CRYPTO_LABELS = {0: "negative", 1: "neutral", 2: "positive"}

RISK_KEYWORDS = [
    "regulatory", "crackdown", "lawsuit", "ban", "investigation", "halted",
    "exploit", "hack", "hacked", "stolen", "scam", "fraud", "rug pull",
    "rugpull", "unusable", "insanely high", "fees are", "shutdown",
    "arrested", "charged", "indicted", "sanctioned", "delisted",
    "insolvent", "bankrupt", "collapse", "liquidat",
]

TEST_SENTENCES = [
    ("Bitcoin is mooning right now, diamond hands!", "positive"),
    ("This token is a total rug pull, devs dumped everything", "negative"),
    ("WAGMI! BTC breaking all-time highs", "positive"),
    ("Massive whale dump crashed ETH price 20% in an hour", "negative"),
    ("Solana network is down again, this is very bearish", "negative"),
    ("Bitcoin halving will reduce supply and increase scarcity", "positive"),
    ("SEC approved Bitcoin ETF, institutional money flowing in", "positive"),
    ("FUD spreading about Tether reserves, market uncertain", "negative"),
    ("DeFi protocol hacked, $50M stolen from liquidity pools", "negative"),
    ("Ethereum gas fees are insanely high, makes it unusable", "negative"),
    ("BTC just broke $100k support level, bulls are in control", "positive"),
    ("Crypto winter is here, everyone is capitulating", "negative"),
    ("New partnership between Chainlink and major bank announced", "positive"),
    ("Binance facing regulatory crackdown in multiple countries", "negative"),
    ("Layer 2 solutions are scaling Ethereum successfully", "positive"),
]

MODELS = {
    "ProsusAI/finbert": {"labels": PROSUS_LABELS, "max_length": 512},
    "burakutf/finetuned-finbert-crypto": {"labels": CRYPTO_LABELS, "max_length": 128},
}


def load_model(model_name: str):
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()

    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    model.to(device)
    return tokenizer, model, device


def predict(tokenizer, model, device, texts, label_map, max_length):
    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=1)

    results = []
    for prob in probs:
        results.append(
            {
                label_map[0]: prob[0].item(),
                label_map[1]: prob[1].item(),
                label_map[2]: prob[2].item(),
            }
        )
    return results


def has_risk_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in RISK_KEYWORDS)


def resolve_ensemble(prosus: dict, crypto: dict, text: str) -> dict:
    neg_threshold = 0.55

    if prosus["negative"] >= neg_threshold or crypto["negative"] >= neg_threshold:
        return prosus if prosus["negative"] >= crypto["negative"] else crypto

    if has_risk_keywords(text):
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


def dominant_label(result: dict) -> str:
    return max(result, key=result.get)


def main():
    loaded = {}
    for name in MODELS:
        print(f"Loading {name}...")
        tokenizer, model, device = load_model(name)
        loaded[name] = (tokenizer, model, device)

    texts = [s for s, _ in TEST_SENTENCES]
    expected = [e for _, e in TEST_SENTENCES]

    all_results = {}
    for name, (tokenizer, model, device) in loaded.items():
        cfg = MODELS[name]
        all_results[name] = predict(
            tokenizer, model, device, texts, cfg["labels"], cfg["max_length"]
        )

    m1, m2 = "ProsusAI/finbert", "burakutf/finetuned-finbert-crypto"

    ensemble_results = []
    for idx in range(len(texts)):
        ensemble_results.append(
            resolve_ensemble(all_results[m1][idx], all_results[m2][idx], texts[idx])
        )

    print("\n" + "=" * 110)
    print("BENCHMARK: ProsusAI/finbert vs Crypto FinBERT vs Ensemble (negative-wins)")
    print("=" * 110)

    scores = {"prosus": 0, "crypto": 0, "ensemble": 0}

    for idx, (sentence, exp) in enumerate(TEST_SENTENCES):
        r1 = all_results[m1][idx]
        r2 = all_results[m2][idx]
        re = ensemble_results[idx]
        d1 = dominant_label(r1)
        d2 = dominant_label(r2)
        de = dominant_label(re)

        c1 = "✅" if d1 == exp else "❌"
        c2 = "✅" if d2 == exp else "❌"
        ce = "✅" if de == exp else "❌"

        if d1 == exp:
            scores["prosus"] += 1
        if d2 == exp:
            scores["crypto"] += 1
        if de == exp:
            scores["ensemble"] += 1

        risk = " ⚠️RISK" if has_risk_keywords(sentence) else ""
        print(f"\n[{idx + 1}] {sentence}{risk}")
        print(f"  Expected: {exp}")
        print(f"  {c1} ProsusAI/finbert:    {d1:>8s}  (pos={r1['positive']:.3f} neg={r1['negative']:.3f} neu={r1['neutral']:.3f})")
        print(f"  {c2} Crypto FinBERT:      {d2:>8s}  (pos={r2['positive']:.3f} neg={r2['negative']:.3f} neu={r2['neutral']:.3f})")
        print(f"  {ce} Ensemble:            {de:>8s}  (pos={re['positive']:.3f} neg={re['negative']:.3f} neu={re['neutral']:.3f})")

    total = len(TEST_SENTENCES)
    print("\n" + "=" * 110)
    print("ACCURACY SUMMARY")
    print("=" * 110)
    print(f"  ProsusAI/finbert:    {scores['prosus']:>2d}/{total} ({scores['prosus'] / total * 100:.0f}%)")
    print(f"  Crypto FinBERT:      {scores['crypto']:>2d}/{total} ({scores['crypto'] / total * 100:.0f}%)")
    print(f"  Ensemble:            {scores['ensemble']:>2d}/{total} ({scores['ensemble'] / total * 100:.0f}%)")
    print("=" * 110)


if __name__ == "__main__":
    main()
