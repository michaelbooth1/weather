# Roadmap Item 6: Feature-Based Probability Model Evaluation

Generated at: 2026-06-06 15:22:52

This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:

1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)

2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)


Lower log loss / Brier is better. ECE (expected calibration error over the
top-class confidence) is reported per model below the table; lower is better.


| Cutoff Hour | Base LogLoss | Base Brier | Base Acc | LR LogLoss | LR Brier | LR Acc | HGBC LogLoss | HGBC Brier | HGBC Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 3.5611 | 0.9699 | 8.6% | 3.5003 | 0.9819 | 7.6% | 3.3362 | 0.9709 | 14.3% |
| 10:00 | 3.5416 | 0.9693 | 8.6% | 3.4586 | 0.9675 | 13.3% | 3.3542 | 0.9703 | 18.1% |
| 12:00 | 3.5332 | 0.9685 | 6.7% | 3.5291 | 0.9794 | 9.5% | 3.4626 | 1.0104 | 13.3% |
| 13:00 | 3.5369 | 0.9684 | 9.5% | 3.4739 | 0.9742 | 8.6% | 3.4378 | 0.9974 | 11.4% |
| 15:00 | 3.5329 | 0.9676 | 9.5% | 3.4336 | 0.9739 | 7.6% | 3.1586 | 0.9580 | 20.0% |
| 16:00 | 3.5347 | 0.9670 | 10.5% | 3.4262 | 0.9762 | 8.6% | 2.7525 | 0.8442 | 31.4% |
| 17:00 | 3.5301 | 0.9656 | 10.5% | 3.4863 | 0.9815 | 3.8% | 2.6666 | 0.8178 | 37.1% |
| 18:00 | 3.5389 | 0.9661 | 9.5% | 3.5291 | 0.9856 | 4.8% | 2.4889 | 0.7121 | 46.7% |
| 20:00 | 3.5115 | 0.9616 | 9.5% | 3.5194 | 0.9805 | 7.6% | 2.3282 | 0.6613 | 55.2% |

## HGB climatology-blend calibration (tuned by LOO log loss)

Blend weight = fraction on the HGB prediction vs the climatology prior. Previously hardcoded at 0.80 for every hour and ignored at inference; now grid-searched per hour and read from the model bundle.

| Cutoff | Tuned w | LogLoss @0.80 | LogLoss @tuned | Delta | ECE @0.80 | ECE @tuned |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 0.60 | 3.3362 | 3.2864 | +0.0498 | 0.1686 | 0.1043 |
| 10:00 | 0.50 | 3.3542 | 3.3083 | +0.0459 | 0.1321 | 0.0745 |
| 12:00 | 0.50 | 3.4626 | 3.3714 | +0.0913 | 0.2021 | 0.1056 |
| 13:00 | 0.50 | 3.4378 | 3.3609 | +0.0769 | 0.1990 | 0.1134 |
| 15:00 | 0.70 | 3.1586 | 3.1462 | +0.0123 | 0.1405 | 0.1183 |
| 16:00 | 0.85 | 2.7525 | 2.7507 | +0.0018 | 0.1522 | 0.1182 |
| 17:00 | 0.85 | 2.6666 | 2.6607 | +0.0060 | 0.0564 | 0.0547 |
| 18:00 | 0.90 | 2.4889 | 2.4780 | +0.0109 | 0.1464 | 0.1775 |
| 20:00 | 0.90 | 2.3282 | 2.3096 | +0.0186 | 0.1912 | 0.1828 |

## Overall calibration (Expected Calibration Error)

| Model | ECE (top-class confidence vs accuracy) |
| :--- | :--- |
| Empirical baseline | 0.0036 |
| Logistic Regression | 0.1056 |
| HGBC (fixed 0.80 blend) | 0.0679 |
| HGBC (tuned blend) | 0.0438 |

## Feature-family ablation (HGB LOO validation)

For each leave-one-out fold, the trained HGB model is held fixed and one feature family is neutralized in the validation row. Positive deltas mean the feature family helped the HGB validation score; negative deltas mean neutralizing it improved the score. This is a fast sensitivity ablation, not a full retrain-without-family study.

| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| observed_temp_path | 945 | 2.9984 | 3.7004 | +0.7020 | 0.8825 | 1.0382 | +0.1557 |
| forecast | 945 | 2.9984 | 3.4368 | +0.4384 | 0.8825 | 0.9478 | +0.0653 |
| cloud_regime | 945 | 2.9984 | 2.9845 | -0.0139 | 0.8825 | 0.8794 | -0.0031 |
| wind_regime | 945 | 2.9984 | 2.9832 | -0.0152 | 0.8825 | 0.8775 | -0.0050 |
| atmosphere | 945 | 2.9984 | 2.9659 | -0.0325 | 0.8825 | 0.8672 | -0.0153 |

### Feature-family ablation by cutoff hour

| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | atmosphere | 105 | 3.3362 | 3.3370 | +0.0008 | 0.9709 | 0.9663 | -0.0046 |
| 09:00 | cloud_regime | 105 | 3.3362 | 3.2983 | -0.0379 | 0.9709 | 0.9669 | -0.0040 |
| 09:00 | forecast | 105 | 3.3362 | 3.8243 | +0.4881 | 0.9709 | 1.0031 | +0.0321 |
| 09:00 | observed_temp_path | 105 | 3.3362 | 3.5671 | +0.2309 | 0.9709 | 1.0121 | +0.0412 |
| 09:00 | wind_regime | 105 | 3.3362 | 3.3576 | +0.0214 | 0.9709 | 0.9705 | -0.0004 |
| 10:00 | atmosphere | 105 | 3.3542 | 3.2851 | -0.0691 | 0.9703 | 0.9633 | -0.0070 |
| 10:00 | cloud_regime | 105 | 3.3542 | 3.3816 | +0.0274 | 0.9703 | 0.9746 | +0.0043 |
| 10:00 | forecast | 105 | 3.3542 | 3.8269 | +0.4727 | 0.9703 | 1.0165 | +0.0462 |
| 10:00 | observed_temp_path | 105 | 3.3542 | 3.4737 | +0.1195 | 0.9703 | 0.9897 | +0.0194 |
| 10:00 | wind_regime | 105 | 3.3542 | 3.3971 | +0.0429 | 0.9703 | 0.9735 | +0.0032 |
| 12:00 | atmosphere | 105 | 3.4626 | 3.4863 | +0.0237 | 1.0104 | 1.0045 | -0.0058 |
| 12:00 | cloud_regime | 105 | 3.4626 | 3.4255 | -0.0371 | 1.0104 | 1.0037 | -0.0067 |
| 12:00 | forecast | 105 | 3.4626 | 3.8065 | +0.3438 | 1.0104 | 1.0123 | +0.0019 |
| 12:00 | observed_temp_path | 105 | 3.4626 | 3.5750 | +0.1123 | 1.0104 | 0.9954 | -0.0149 |
| 12:00 | wind_regime | 105 | 3.4626 | 3.5097 | +0.0471 | 1.0104 | 1.0100 | -0.0004 |
| 13:00 | atmosphere | 105 | 3.4378 | 3.4182 | -0.0196 | 0.9974 | 0.9868 | -0.0106 |
| 13:00 | cloud_regime | 105 | 3.4378 | 3.3966 | -0.0413 | 0.9974 | 0.9908 | -0.0067 |
| 13:00 | forecast | 105 | 3.4378 | 3.8913 | +0.4535 | 0.9974 | 1.0261 | +0.0287 |
| 13:00 | observed_temp_path | 105 | 3.4378 | 3.6315 | +0.1937 | 0.9974 | 1.0109 | +0.0134 |
| 13:00 | wind_regime | 105 | 3.4378 | 3.4057 | -0.0322 | 0.9974 | 0.9870 | -0.0104 |
| 15:00 | atmosphere | 105 | 3.1586 | 3.0695 | -0.0890 | 0.9580 | 0.9238 | -0.0343 |
| 15:00 | cloud_regime | 105 | 3.1586 | 3.1723 | +0.0137 | 0.9580 | 0.9578 | -0.0002 |
| 15:00 | forecast | 105 | 3.1586 | 3.5182 | +0.3596 | 0.9580 | 0.9746 | +0.0166 |
| 15:00 | observed_temp_path | 105 | 3.1586 | 3.7437 | +0.5851 | 0.9580 | 1.0701 | +0.1121 |
| 15:00 | wind_regime | 105 | 3.1586 | 3.1200 | -0.0386 | 0.9580 | 0.9457 | -0.0123 |
| 16:00 | atmosphere | 105 | 2.7525 | 2.8165 | +0.0640 | 0.8442 | 0.8473 | +0.0032 |
| 16:00 | cloud_regime | 105 | 2.7525 | 2.7581 | +0.0056 | 0.8442 | 0.8452 | +0.0011 |
| 16:00 | forecast | 105 | 2.7525 | 3.1895 | +0.4370 | 0.8442 | 0.9229 | +0.0788 |
| 16:00 | observed_temp_path | 105 | 2.7525 | 3.7992 | +1.0468 | 0.8442 | 1.0610 | +0.2169 |
| 16:00 | wind_regime | 105 | 2.7525 | 2.7516 | -0.0008 | 0.8442 | 0.8536 | +0.0095 |
| 17:00 | atmosphere | 105 | 2.6666 | 2.5737 | -0.0929 | 0.8178 | 0.7797 | -0.0381 |
| 17:00 | cloud_regime | 105 | 2.6666 | 2.6373 | -0.0293 | 0.8178 | 0.8072 | -0.0106 |
| 17:00 | forecast | 105 | 2.6666 | 3.1275 | +0.4609 | 0.8178 | 0.9330 | +0.1152 |
| 17:00 | observed_temp_path | 105 | 2.6666 | 3.8025 | +1.1358 | 0.8178 | 1.0684 | +0.2506 |
| 17:00 | wind_regime | 105 | 2.6666 | 2.6192 | -0.0474 | 0.8178 | 0.8117 | -0.0061 |
| 18:00 | atmosphere | 105 | 2.4889 | 2.3846 | -0.1043 | 0.7121 | 0.6685 | -0.0436 |
| 18:00 | cloud_regime | 105 | 2.4889 | 2.4706 | -0.0183 | 0.7121 | 0.7119 | -0.0002 |
| 18:00 | forecast | 105 | 2.4889 | 2.8794 | +0.3905 | 0.7121 | 0.8277 | +0.1156 |
| 18:00 | observed_temp_path | 105 | 2.4889 | 3.8698 | +1.3810 | 0.7121 | 1.0769 | +0.3648 |
| 18:00 | wind_regime | 105 | 2.4889 | 2.3975 | -0.0914 | 0.7121 | 0.6907 | -0.0214 |
| 20:00 | atmosphere | 105 | 2.3282 | 2.3227 | -0.0056 | 0.6613 | 0.6646 | +0.0033 |
| 20:00 | cloud_regime | 105 | 2.3282 | 2.3203 | -0.0079 | 0.6613 | 0.6569 | -0.0044 |
| 20:00 | forecast | 105 | 2.3282 | 2.8676 | +0.5394 | 0.6613 | 0.8140 | +0.1527 |
| 20:00 | observed_temp_path | 105 | 2.3282 | 3.8408 | +1.5126 | 0.6613 | 1.0595 | +0.3982 |
| 20:00 | wind_regime | 105 | 2.3282 | 2.2903 | -0.0379 | 0.6613 | 0.6548 | -0.0065 |
