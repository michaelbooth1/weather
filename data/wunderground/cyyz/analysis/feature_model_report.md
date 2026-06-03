# Roadmap Item 6: Feature-Based Probability Model Evaluation

Generated at: 2026-05-31 12:02:48

This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:

1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)

2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)


Lower log loss / Brier is better. ECE (expected calibration error over the
top-class confidence) is reported per model below the table; lower is better.


| Cutoff Hour | Base LogLoss | Base Brier | Base Acc | LR LogLoss | LR Brier | LR Acc | HGBC LogLoss | HGBC Brier | HGBC Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 2.8679 | 0.9311 | 15.1% | 2.4856 | 0.8984 | 15.6% | 2.5883 | 0.9326 | 15.9% |
| 10:00 | 2.8193 | 0.9248 | 11.4% | 2.4525 | 0.8957 | 15.0% | 2.5271 | 0.9328 | 19.2% |
| 12:00 | 2.7335 | 0.9116 | 21.9% | 2.3758 | 0.8834 | 17.5% | 2.2246 | 0.8754 | 24.3% |
| 13:00 | 2.6348 | 0.8963 | 28.4% | 2.3707 | 0.8835 | 17.9% | 2.0301 | 0.8389 | 28.4% |
| 15:00 | 2.3238 | 0.8318 | 62.3% | 2.3261 | 0.8752 | 20.7% | 1.3977 | 0.6137 | 53.5% |
| 16:00 | 2.0817 | 0.7664 | 80.8% | 2.3042 | 0.8681 | 20.7% | 0.9869 | 0.3693 | 78.4% |
| 17:00 | 1.9348 | 0.7286 | 89.0% | 2.3127 | 0.8695 | 21.0% | 0.6893 | 0.2255 | 87.5% |
| 18:00 | 1.8535 | 0.7094 | 92.7% | 2.2986 | 0.8670 | 21.5% | 0.5257 | 0.1511 | 92.1% |
| 20:00 | 1.8013 | 0.6960 | 95.2% | 2.3323 | 0.8769 | 19.8% | 0.4181 | 0.1050 | 95.4% |

## HGB climatology-blend calibration (tuned by LOO log loss)

Blend weight = fraction on the HGB prediction vs the climatology prior. Previously hardcoded at 0.80 for every hour and ignored at inference; now grid-searched per hour and read from the model bundle.

| Cutoff | Tuned w | LogLoss @0.80 | LogLoss @tuned | Delta | ECE @0.80 | ECE @tuned |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 0.80 | 2.5883 | 2.5883 | +0.0000 | 0.1671 | 0.1671 |
| 10:00 | 0.80 | 2.5271 | 2.5271 | +0.0000 | 0.1619 | 0.1619 |
| 12:00 | 0.97 | 2.2246 | 2.1851 | +0.0395 | 0.1354 | 0.2005 |
| 13:00 | 0.97 | 2.0301 | 1.9717 | +0.0584 | 0.1254 | 0.1969 |
| 15:00 | 0.97 | 1.3977 | 1.2883 | +0.1094 | 0.0363 | 0.0860 |
| 16:00 | 0.97 | 0.9869 | 0.8726 | +0.1143 | 0.1350 | 0.0448 |
| 17:00 | 0.97 | 0.6893 | 0.5576 | +0.1317 | 0.1586 | 0.0307 |
| 18:00 | 0.97 | 0.5257 | 0.3738 | +0.1519 | 0.1809 | 0.0406 |
| 20:00 | 0.97 | 0.4181 | 0.2466 | +0.1715 | 0.1896 | 0.0488 |

## Overall calibration (Expected Calibration Error)

| Model | ECE (top-class confidence vs accuracy) |
| :--- | :--- |
| Empirical baseline | 0.4103 |
| Logistic Regression | 0.0392 |
| HGBC (fixed 0.80 blend) | 0.1096 |
| HGBC (tuned blend) | 0.0948 |

## Feature-family ablation (HGB LOO validation)

For each leave-one-out fold, the trained HGB model is held fixed and one feature family is neutralized in the validation row. Positive deltas mean the feature family helped the HGB validation score; negative deltas mean neutralizing it improved the score. This is a fast sensitivity ablation, not a full retrain-without-family study.

| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| observed_temp_path | 5823 | 1.4875 | 3.8783 | +2.3907 | 0.5605 | 1.2654 | +0.7049 |
| wind_regime | 5823 | 1.4875 | 1.5143 | +0.0267 | 0.5605 | 0.5703 | +0.0098 |
| forecast | 5823 | 1.4875 | 1.5055 | +0.0179 | 0.5605 | 0.5631 | +0.0026 |
| atmosphere | 5823 | 1.4875 | 1.4950 | +0.0074 | 0.5605 | 0.5622 | +0.0017 |
| cloud_regime | 5823 | 1.4875 | 1.4860 | -0.0016 | 0.5605 | 0.5596 | -0.0009 |

### Feature-family ablation by cutoff hour

| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | atmosphere | 647 | 2.5883 | 2.5480 | -0.0404 | 0.9326 | 0.9143 | -0.0183 |
| 09:00 | cloud_regime | 647 | 2.5883 | 2.5816 | -0.0067 | 0.9326 | 0.9331 | +0.0005 |
| 09:00 | forecast | 647 | 2.5883 | 2.6677 | +0.0793 | 0.9326 | 0.9491 | +0.0165 |
| 09:00 | observed_temp_path | 647 | 2.5883 | 3.3248 | +0.7365 | 0.9326 | 1.0130 | +0.0804 |
| 09:00 | wind_regime | 647 | 2.5883 | 2.6194 | +0.0311 | 0.9326 | 0.9334 | +0.0007 |
| 10:00 | atmosphere | 647 | 2.5271 | 2.5427 | +0.0157 | 0.9328 | 0.9406 | +0.0078 |
| 10:00 | cloud_regime | 647 | 2.5271 | 2.5149 | -0.0121 | 0.9328 | 0.9274 | -0.0054 |
| 10:00 | forecast | 647 | 2.5271 | 2.5970 | +0.0700 | 0.9328 | 0.9448 | +0.0120 |
| 10:00 | observed_temp_path | 647 | 2.5271 | 3.4270 | +0.8999 | 0.9328 | 1.0301 | +0.0973 |
| 10:00 | wind_regime | 647 | 2.5271 | 2.5521 | +0.0251 | 0.9328 | 0.9396 | +0.0068 |
| 12:00 | atmosphere | 647 | 2.2246 | 2.3067 | +0.0821 | 0.8754 | 0.8979 | +0.0225 |
| 12:00 | cloud_regime | 647 | 2.2246 | 2.2273 | +0.0027 | 0.8754 | 0.8733 | -0.0020 |
| 12:00 | forecast | 647 | 2.2246 | 2.2440 | +0.0193 | 0.8754 | 0.8780 | +0.0026 |
| 12:00 | observed_temp_path | 647 | 2.2246 | 3.5693 | +1.3447 | 0.8754 | 1.0754 | +0.2000 |
| 12:00 | wind_regime | 647 | 2.2246 | 2.3005 | +0.0759 | 0.8754 | 0.8889 | +0.0135 |
| 13:00 | atmosphere | 647 | 2.0301 | 1.9701 | -0.0600 | 0.8389 | 0.8089 | -0.0300 |
| 13:00 | cloud_regime | 647 | 2.0301 | 2.0336 | +0.0035 | 0.8389 | 0.8405 | +0.0016 |
| 13:00 | forecast | 647 | 2.0301 | 2.0356 | +0.0055 | 0.8389 | 0.8383 | -0.0006 |
| 13:00 | observed_temp_path | 647 | 2.0301 | 3.6690 | +1.6389 | 0.8389 | 1.0862 | +0.2473 |
| 13:00 | wind_regime | 647 | 2.0301 | 2.0146 | -0.0155 | 0.8389 | 0.8297 | -0.0092 |
| 15:00 | atmosphere | 647 | 1.3977 | 1.4086 | +0.0108 | 0.6137 | 0.6236 | +0.0098 |
| 15:00 | cloud_regime | 647 | 1.3977 | 1.3903 | -0.0075 | 0.6137 | 0.6110 | -0.0027 |
| 15:00 | forecast | 647 | 1.3977 | 1.3909 | -0.0069 | 0.6137 | 0.6099 | -0.0039 |
| 15:00 | observed_temp_path | 647 | 1.3977 | 3.9414 | +2.5436 | 0.6137 | 1.2557 | +0.6420 |
| 15:00 | wind_regime | 647 | 1.3977 | 1.4623 | +0.0646 | 0.6137 | 0.6460 | +0.0323 |
| 16:00 | atmosphere | 647 | 0.9869 | 1.0153 | +0.0283 | 0.3693 | 0.3816 | +0.0123 |
| 16:00 | cloud_regime | 647 | 0.9869 | 0.9923 | +0.0054 | 0.3693 | 0.3695 | +0.0002 |
| 16:00 | forecast | 647 | 0.9869 | 0.9870 | +0.0001 | 0.3693 | 0.3674 | -0.0018 |
| 16:00 | observed_temp_path | 647 | 0.9869 | 4.0803 | +3.0933 | 0.3693 | 1.3876 | +1.0183 |
| 16:00 | wind_regime | 647 | 0.9869 | 1.0110 | +0.0240 | 0.3693 | 0.3865 | +0.0172 |
| 17:00 | atmosphere | 647 | 0.6893 | 0.7041 | +0.0148 | 0.2255 | 0.2292 | +0.0037 |
| 17:00 | cloud_regime | 647 | 0.6893 | 0.6931 | +0.0038 | 0.2255 | 0.2257 | +0.0001 |
| 17:00 | forecast | 647 | 0.6893 | 0.6894 | +0.0001 | 0.2255 | 0.2256 | +0.0001 |
| 17:00 | observed_temp_path | 647 | 0.6893 | 4.2860 | +3.5968 | 0.2255 | 1.5103 | +1.2848 |
| 17:00 | wind_regime | 647 | 0.6893 | 0.7128 | +0.0235 | 0.2255 | 0.2408 | +0.0153 |
| 18:00 | atmosphere | 647 | 0.5257 | 0.5325 | +0.0068 | 0.1511 | 0.1529 | +0.0019 |
| 18:00 | cloud_regime | 647 | 0.5257 | 0.5239 | -0.0018 | 0.1511 | 0.1506 | -0.0004 |
| 18:00 | forecast | 647 | 0.5257 | 0.5214 | -0.0043 | 0.1511 | 0.1498 | -0.0013 |
| 18:00 | observed_temp_path | 647 | 0.5257 | 4.2986 | +3.7729 | 0.1511 | 1.5141 | +1.3630 |
| 18:00 | wind_regime | 647 | 0.5257 | 0.5436 | +0.0179 | 0.1511 | 0.1641 | +0.0130 |
| 20:00 | atmosphere | 647 | 0.4181 | 0.4267 | +0.0085 | 0.1050 | 0.1108 | +0.0058 |
| 20:00 | cloud_regime | 647 | 0.4181 | 0.4167 | -0.0014 | 0.1050 | 0.1048 | -0.0002 |
| 20:00 | forecast | 647 | 0.4181 | 0.4163 | -0.0018 | 0.1050 | 0.1046 | -0.0004 |
| 20:00 | observed_temp_path | 647 | 0.4181 | 4.3081 | +3.8899 | 0.1050 | 1.5162 | +1.4111 |
| 20:00 | wind_regime | 647 | 0.4181 | 0.4121 | -0.0060 | 0.1050 | 0.1038 | -0.0012 |
