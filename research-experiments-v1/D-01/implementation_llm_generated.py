"""D-01 Multi-condition Text Classification Reproduction Implementation.

Strictly implemented using Python 3.9 standard library (math, re, collections).
Conforms to method.md and protocol.json specifications:
- Tokenizer: lowercase regex [a-z0-9]+
- Vocabulary & IDF fitted only on the current training condition; vocabulary sorted lexicographically
- IDF formula: IDF(t) = 1.0 + ln((1 + N) / (1 + df(t)))
- Feature vector: raw TF * IDF, L2 normalized, bias=1.0 appended at the end
- Softmax linear model: classes sorted lexicographically, zero initialization
- Loss: average cross entropy + penalty/2 * sum(W^2) (including bias)
- Update rule: full-batch gradient descent W -= lr * (grad_sum / N + penalty * W)
- Tie-breaking: lexicographically smallest class for both candidate and baseline predictions
"""

import math
import re
from collections import Counter
from typing import Any, Dict, List


def tokenize(text: Any) -> List[str]:
    """Tokenize text using lowercase regex [a-z0-9]+."""
    return re.findall(r"[a-z0-9]+", str(text).lower())


def run_experiment(request: Dict[str, Any]) -> Dict[str, Any]:
    """Run D-01 multi-condition text classification reproduction experiment."""
    data = request.get("data", {})
    train = data.get("train", [])
    texts = data.get("texts", [])
    protocol = request.get("protocol", {})

    epochs = int(protocol.get("epochs", 100))
    lr = float(protocol.get("learning_rate", 0.8))
    penalty = float(protocol.get("penalty", 0.001))

    # 1. Classes and baseline majority class
    classes = sorted(list(set(d.get("label", "") for d in train)))
    K = len(classes)
    class_to_idx = {c: i for i, c in enumerate(classes)}

    if K == 0:
        return {
            "baseline": ["" for _ in texts],
            "candidate": ["" for _ in texts],
            "details": {
                "classes": [],
                "vocabulary": [],
                "idf": [],
                "weights": [],
            },
        }

    label_counts = Counter(d.get("label", "") for d in train)
    # Tie-breaking for baseline: lexicographically smallest class among tied counts
    majority_class = min(classes, key=lambda c: (-label_counts[c], c))
    baseline = [majority_class for _ in texts]

    # 2. Vocabulary & IDF calculation (fitted ONLY on current training set)
    N = len(train)
    df = Counter()
    for item in train:
        tokens_set = set(tokenize(item.get("text", "")))
        for t in tokens_set:
            df[t] += 1

    vocabulary = sorted(list(df.keys()))
    V = len(vocabulary)
    token_to_idx = {t: i for i, t in enumerate(vocabulary)}

    # IDF = 1.0 + ln((1 + N) / (1 + df))
    idf = {t: 1.0 + math.log((1.0 + N) / (1.0 + df[t])) for t in vocabulary}
    idf_list = [idf[t] for t in vocabulary]

    # Feature vectorizer: raw TF * IDF, L2 normalized, append bias=1.0 at index V
    def vectorize(text: Any):
        tokens = tokenize(text)
        counts = Counter(tokens)
        feats = {}
        sum_sq = 0.0
        for t, c in counts.items():
            if t in token_to_idx:
                idx = token_to_idx[t]
                val = float(c) * idf[t]
                feats[idx] = val
                sum_sq += val * val
        if sum_sq > 0.0:
            norm = math.sqrt(sum_sq)
            feats = {idx: val / norm for idx, val in feats.items()}
        else:
            feats = {}
        # Sparse features + bias at index V
        return list(feats.items()) + [(V, 1.0)]

    # 3. Model Training: Multiclass Softmax Linear Model
    if K == 1 or N == 0:
        W = [[0.0] * (V + 1) for _ in range(K)]
    else:
        X_train = [vectorize(item.get("text", "")) for item in train]
        Y_train = [class_to_idx[item.get("label", "")] for item in train]
        W = [[0.0] * (V + 1) for _ in range(K)]
        inv_N = 1.0 / N

        for _ in range(epochs):
            grad_W = [[0.0] * (V + 1) for _ in range(K)]
            for i in range(N):
                feats = X_train[i]
                target_k = Y_train[i]
                z = [0.0] * K
                for k in range(K):
                    wk = W[k]
                    dot = 0.0
                    for col, val in feats:
                        dot += wk[col] * val
                    z[k] = dot
                max_z = max(z)
                exp_z = [math.exp(zk - max_z) for zk in z]
                sum_exp = sum(exp_z)
                for k in range(K):
                    p_k = exp_z[k] / sum_exp
                    diff = p_k - (1.0 if k == target_k else 0.0)
                    if diff != 0.0:
                        gk = grad_W[k]
                        for col, val in feats:
                            gk[col] += diff * val

            # W -= lr * (grad_W / N + penalty * W)
            for k in range(K):
                wk = W[k]
                gk = grad_W[k]
                for j in range(V + 1):
                    wk[j] -= lr * (gk[j] * inv_N + penalty * wk[j])

    # 4. Candidate Predictions
    candidate = []
    for text in texts:
        if K == 1:
            candidate.append(classes[0])
            continue
        feats = vectorize(text)
        z = [0.0] * K
        for k in range(K):
            wk = W[k]
            dot = 0.0
            for col, val in feats:
                dot += wk[col] * val
            z[k] = dot
        # Tie-breaking: pick class with lexicographically smallest name
        best_k = min(range(K), key=lambda k: (-z[k], classes[k]))
        candidate.append(classes[best_k])

    return {
        "baseline": baseline,
        "candidate": candidate,
        "details": {
            "classes": classes,
            "vocabulary": vocabulary,
            "idf": idf_list,
            "weights": W,
        },
    }