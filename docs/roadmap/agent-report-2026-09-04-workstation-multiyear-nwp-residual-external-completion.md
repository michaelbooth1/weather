# EXTERNAL_DIRECTION_CONSISTENT

**Verdict: `EXTERNAL_DIRECTION_CONSISTENT`.** The already-fitted eleven-field
residual challenger has positive MSE-improvement point estimates in both the
pre-boundary and post-boundary cohorts, for both frozen primary leads 2-7 and
the leads 1-7 sensitivity. This is external-secondary directional evidence.
It is not confirmation, changes no original conclusion, and authorizes no
release, distribution, serving, alpha, promotion, or live use. The original
2025 verdict remains `INCONCLUSIVE_UNDERPOWERED`.

Every primary and sensitivity MAE/MSE improvement 95% crossed-bootstrap
interval crosses zero. The four MSE signs satisfy only the frozen directional
rule; they do not establish a statistically resolved advantage.

## Support and evidence boundary

| Cohort | Dates | Admitted market-days | Old frozen WU | Protected export | Exclusions |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Pre-boundary, 2026-06-03 through 2026-07-30 | 58 | 694 | 612 | 82 | 2 |
| Post-boundary directional, 2026-07-31 through 2026-08-09 | 10 | 120 | 108 | 12 | 0 |
| Exact union | 68 | 814 | 720 | 94 | 2 |

The requested surface was exactly 816 market-date cells across all 12 markets.
The two exclusions are Atlanta and Miami on 2026-06-06, each with 15 configured
WU daily rows against the frozen minimum of 18. Their outcome values were not
parsed or imputed. The 94 protected-export keys had zero overlap with the 720
old admitted keys and retained the exact 82/12 cohort split. No date crossed
the `b77cfbed` / 2026-07-31 boundary, and no pooled headline was computed.

The old mirror was opened once per market: 720 admitted 2026 values were parsed,
the two excluded values were not parsed, and 69,440 non-2026 rows were skipped
without outcome-value access. The protected payload was opened once and exactly
94 values were parsed. Total semantic source opens were 13. Outcome-value
access for 2025 was exactly zero.

## Frozen directional decision endpoints

| Cohort / endpoint | Point | 95% lower | 95% upper | Power | MDE 80% |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Pre, primary MAE improvement | 0.07736464556183223 | -0.02991344000132488 | 0.19125114430451576 | 0.2784823567642648 | 0.15805473342330886 |
| Pre, primary MSE improvement | 0.4190825100325802 | -0.0409843382055485 | 0.9678143455319986 | 0.3742185242330315 | 0.7164180061432767 |
| Pre, leads 1-7 MAE improvement | 0.06194231742318309 | -0.06163917016974144 | 0.19955570723009333 | 0.15469878562600137 | 0.1855035067031594 |
| Pre, leads 1-7 MSE improvement | 0.40431171394222276 | -0.0802265914220001 | 0.9751688179885997 | 0.323009787565929 | 0.755186613895964 |
| Post, primary MAE improvement | 0.07081872036276611 | -0.09531913958370344 | 0.2552074743793751 | 0.12565327719423958 | 0.24843497822321967 |
| Post, primary MSE improvement | 0.3681200047973191 | -0.1541727382086434 | 0.9501007586062451 | 0.2586034072440725 | 0.7868780683079264 |
| Post, leads 1-7 MAE improvement | 0.026524971219328463 | -0.1588767667712883 | 0.20497243989187325 | 0.05953642426758032 | 0.25827688154184913 |
| Post, leads 1-7 MSE improvement | 0.18237465147806686 | -0.30080980163365734 | 0.7197636825004038 | 0.10958810706022448 | 0.7188117115870056 |

Units are Celsius-equivalent MAE/signed error and squared Celsius-equivalent
MSE. Improvement is baseline loss minus challenger loss. The frozen method is
a shared-weight crossed target-date x market pigeonhole bootstrap with 20,000
draws, seed 8802026, percentile 95% intervals, two-sided normal plug-in power at
alpha 0.05, and `MDE80 = (z0.975 + z0.8) * crossed bootstrap SE`.

## All frozen metric endpoints

The following tables report every frozen endpoint, including point, percentile
95% interval, crossed-bootstrap standard error, achieved power, and 80% MDE.

### Pre-boundary

| Endpoint | Point | 95% lower | 95% upper | SE | Power | MDE 80% |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_leads_eleven_field_residual_challenger_native__mae` | 1.3337734070446206 | 1.1452631015988772 | 1.5291789499309381 | 0.098631166661714439 | 1 | 0.27632361856469584 |
| `all_leads_eleven_field_residual_challenger_native__signed_error` | -0.021962350696745059 | -0.3977465816955163 | 0.36884155121772033 | 0.1958459828979339 | 0.0514418013688116 | 0.54867921071365677 |
| `all_leads_eleven_field_residual_challenger_native__squared_error` | 3.0712353167303692 | 2.2210715449542189 | 4.0819473316013211 | 0.47627683655373237 | 0.99999641301750275 | 1.334330145018543 |
| `all_leads_raw_temperature_anchor_native__mae` | 1.8775056035862951 | 1.4421727330779053 | 2.461181134086734 | 0.262705649295401 | 0.99999989305344061 | 0.735992263780765 |
| `all_leads_raw_temperature_anchor_native__signed_error` | 1.4518892090938202 | 0.88200706284929431 | 2.1486966406326142 | 0.3208747786415676 | 0.9948385398919708 | 0.89895803670748664 |
| `all_leads_raw_temperature_anchor_native__squared_error` | 6.6053088198669379 | 3.6437513110516839 | 11.197900715730094 | 1.9855533906788672 | 0.91414353124293724 | 5.562697029099998 |
| `all_leads_sensitivity__mae_improvement` | 0.061942317423183089 | -0.061639170169741443 | 0.19955570723009333 | 0.066213765515263132 | 0.15469878562600137 | 0.1855035067031594 |
| `all_leads_sensitivity__squared_error_improvement` | 0.40431171394222271 | -0.0802265914220001 | 0.97516881798859956 | 0.26955689550811751 | 0.323009787565929 | 0.755186613895964 |
| `all_leads_temperature_residual_baseline_native__mae` | 1.3957157244678038 | 1.1532272661004983 | 1.662046266094475 | 0.13105313367258656 | 1 | 0.36715652208450139 |
| `all_leads_temperature_residual_baseline_native__signed_error` | -0.061651616764669973 | -0.4783149576911046 | 0.3774799599181497 | 0.21923166516357021 | 0.059107843280969741 | 0.61419619246455 |
| `all_leads_temperature_residual_baseline_native__squared_error` | 3.4755470306725922 | 2.3262992957406761 | 4.8658185835109258 | 0.65288585462008175 | 0.999615052083512 | 1.8291153594186735 |
| `eleven_field_residual_challenger_native__mae` | 1.3759529054459962 | 1.1771502097003874 | 1.5811694306060089 | 0.10343706760759495 | 1 | 0.28978775961438974 |
| `eleven_field_residual_challenger_native__signed_error` | 0.076891420800502153 | -0.301568205826747 | 0.465276196325392 | 0.19628645473532463 | 0.067757398796784 | 0.54991323010228588 |
| `eleven_field_residual_challenger_native__squared_error` | 3.2919981089319288 | 2.357229484013537 | 4.3921723236744716 | 0.51835949168270368 | 0.99999435424872718 | 1.4522282895668148 |
| `primary__mae_improvement` | 0.077364645561832229 | -0.029913440001324881 | 0.19125114430451576 | 0.056416179097977949 | 0.2784823567642648 | 0.15805473342330886 |
| `primary__squared_error_improvement` | 0.41908251003258018 | -0.0409843382055485 | 0.96781434553199863 | 0.25571879859711216 | 0.37421852423303148 | 0.71641800614327666 |
| `raw_temperature_anchor_native__mae` | 2.02136567403138 | 1.548737748829903 | 2.6420033125798197 | 0.28131168185526606 | 0.99999991317531722 | 0.78811864956821154 |
| `raw_temperature_anchor_native__signed_error` | 1.5688360550752485 | 0.9464102816013088 | 2.3115709156812474 | 0.34592993872399808 | 0.99499035112888123 | 0.969152202831878 |
| `raw_temperature_anchor_native__squared_error` | 7.5321608940833249 | 4.20243753118618 | 12.627638322293688 | 2.22104385161256 | 0.923828875819219 | 6.2224436234584406 |
| `temperature_residual_baseline_native__mae` | 1.4533175510078289 | 1.2063305717573169 | 1.7120575979286647 | 0.13029826165846159 | 1 | 0.36504168380816171 |
| `temperature_residual_baseline_native__signed_error` | 0.0769750227528818 | -0.35979126681738077 | 0.53028133671293831 | 0.22697509622741169 | 0.063276758492962659 | 0.63589007447048518 |
| `temperature_residual_baseline_native__squared_error` | 3.7110806189645089 | 2.5263160677390197 | 5.1223176432628161 | 0.66329898789934694 | 0.9998609663296 | 1.8582886396881031 |

### Post-boundary directional

| Endpoint | Point | 95% lower | 95% upper | SE | Power | MDE 80% |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_leads_eleven_field_residual_challenger_native__mae` | 1.2119589197826479 | 0.88901929845827254 | 1.6276327735074481 | 0.18908264198877303 | 0.99999570077187638 | 0.529731134797493 |
| `all_leads_eleven_field_residual_challenger_native__signed_error` | -0.0493346376557749 | -0.51097531351604775 | 0.43007191955154522 | 0.2401671679738227 | 0.054847716849827588 | 0.672848787671516 |
| `all_leads_eleven_field_residual_challenger_native__squared_error` | 2.5750339747276949 | 1.2362187528113184 | 4.7895947501991207 | 0.92550996109858163 | 0.79455440605091421 | 2.5928950262300945 |
| `all_leads_raw_temperature_anchor_native__mae` | 2.5675925925925922 | 1.6620370370370372 | 3.8904953703703686 | 0.58374542312131783 | 0.99262614834529839 | 1.6354125485577842 |
| `all_leads_raw_temperature_anchor_native__signed_error` | 2.3840740740740736 | 1.3667569444444441 | 3.7828981481481447 | 0.62652849122368626 | 0.9674993092775912 | 1.7552729597389 |
| `all_leads_raw_temperature_anchor_native__squared_error` | 12.127148148148148 | 4.1570459362139918 | 27.600670653292148 | 6.4462194094524312 | 0.46870347572406645 | 18.05963301023484 |
| `all_leads_sensitivity__mae_improvement` | 0.026524971219328463 | -0.15887676677128831 | 0.20497243989187325 | 0.092189550355999419 | 0.059536424267580323 | 0.25827688154184913 |
| `all_leads_sensitivity__squared_error_improvement` | 0.18237465147806689 | -0.30080980163365734 | 0.71976368250040379 | 0.25657320967418845 | 0.10958810706022448 | 0.71881171158700563 |
| `all_leads_temperature_residual_baseline_native__mae` | 1.2384838910019766 | 0.90196066267862263 | 1.6475033980013538 | 0.18860536324091479 | 0.99999795319248475 | 0.52839399771257389 |
| `all_leads_temperature_residual_baseline_native__signed_error` | -0.14474084909035945 | -0.62068605863911874 | 0.3635297512378115 | 0.251046506251711 | 0.088867088334662947 | 0.70332818097369842 |
| `all_leads_temperature_residual_baseline_native__squared_error` | 2.7574086262057618 | 1.4148312388916195 | 4.8732607757778865 | 0.88371448489128879 | 0.87703365602495187 | 2.4758014379037507 |
| `eleven_field_residual_challenger_native__mae` | 1.2282576313635829 | 0.90568369944947835 | 1.6345355002653652 | 0.18504195571213647 | 0.99999854987921843 | 0.51841080785383609 |
| `eleven_field_residual_challenger_native__signed_error` | 0.15413006518025171 | -0.2892199004938128 | 0.62557387102169582 | 0.23183122665423037 | 0.10197325567083082 | 0.649494937691489 |
| `eleven_field_residual_challenger_native__squared_error` | 2.6856689926851538 | 1.271959982814729 | 4.947127467721816 | 0.94794729514855436 | 0.808717706096837 | 2.6557551296383615 |
| `primary__mae_improvement` | 0.07081872036276611 | -0.095319139583703444 | 0.25520747437937508 | 0.08867657375439579 | 0.12565327719423958 | 0.24843497822321969 |
| `primary__squared_error_improvement` | 0.3681200047973191 | -0.15417273820864341 | 0.95010075860624521 | 0.28086886781831855 | 0.25860340724407249 | 0.78687806830792639 |
| `raw_temperature_anchor_native__mae` | 2.7479166666666668 | 1.8518958333333329 | 4.0489004629629619 | 0.57440303264955 | 0.99762849376236784 | 1.60923904551024 |
| `raw_temperature_anchor_native__signed_error` | 2.5766203703703705 | 1.5605555555555559 | 3.9495717592592561 | 0.61811157068856415 | 0.98639779066144917 | 1.7316922395856704 |
| `raw_temperature_anchor_native__squared_error` | 13.072713734567902 | 4.9233307227366243 | 28.727018351337417 | 6.5173003572171107 | 0.51833521665360727 | 18.258772342781825 |
| `temperature_residual_baseline_native__mae` | 1.2990763517263491 | 0.94669693430999458 | 1.7153413053426547 | 0.19626987938778528 | 0.99999841019553959 | 0.54986679285363438 |
| `temperature_residual_baseline_native__signed_error` | 0.1901989512914905 | -0.31276128825253274 | 0.73006578201349059 | 0.26487307504395335 | 0.1108416350734478 | 0.74206449171926669 |
| `temperature_residual_baseline_native__squared_error` | 3.053788997482473 | 1.5771562521185469 | 5.25086898426062 | 0.94014435352090675 | 0.90117042703865424 | 2.633894523716545 |

## Exact model, design, and input identities

- Mission SHA-256: `5824c7123d837f80cb4ffd9c80fb594e058b8b3bcb807557a09e57b10a77b36b`.
- Source tip/tree: `734f14adba7055ba7459db8a9ab4a16983a1b202` /
  `1468c089b62e09a09a13006a1936c32787e4c64b`.
- Final implementation tip/tree: `8741047c8eca9ebbc31fc7178c1eafe0ac8ae457` /
  `5473d10d3ce90c72019f5b70acc188d20973639d`.
- Source terminal receipt SHA-256:
  `61552b4157cbe899cdaef05f12a3161b4b2898960a095c79445a6692d500e0c2`.
- Source complete-history bundle SHA-256:
  `0fa455f058c2663e3d8d8ea9d9b66212fe6422ec3aa08f9bf1d0b9a9b9e9f8ef`.
- Completion amendment file/self SHA-256:
  `26075a650aabd554d923d98423bcaeb0144cbd3c1fd3adc828957b4b82a6a938` /
  `5d6c9c1f44c4938b9d45e1c8329a213e0f57241f6fbb3c533a33ee68a1ff9171`.
  It recorded `outcome_values_parsed_before_freeze = 0` and binds the exact
  final-attempt commit through the create-only seal.
- Frozen design file/self SHA-256:
  `0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65` /
  `bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb`.
- Prior external amendment file/self SHA-256:
  `866d7537440c6d1921128deff04e04ecc03f9bcc6f0b904b0fa1489e302ac152` /
  `34be1c1eb27d4a563baef3da00e6c24b9bb3e009f5fc7e41b5329b37f7bfa0e0`.
- Prior evaluator SHA-256:
  `471d8dbd0f0adf97d040ec2351b6ad1b182934dcdc6296ceb8f71a20c69b469f`;
  frozen feature module SHA-256:
  `8b513188aa5a123f29c3225d2a8efa435a56b46a07c1bcc0f8a96e756641e27f`.
- Baseline model SHA-256:
  `c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797`;
  challenger model SHA-256:
  `0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5`.
- Baseline/challenger/combined feature-order SHA-256:
  `4e35fe7e2d44d37e22ff02b2b681c2de840a487d1eeddef7cace58b2852bf603` /
  `5839aa7373cdd78d4d54cccfa27d7d8b42ffb8acc5d80e08135561335fa2c3fb` /
  `3d2b3fa4a9b58f7881b80609234904f54fd2db05b21c1f96aac10b5389859bbd`.
- Corpus manifest/payload-inventory/CSV-inventory/transfer SHA-256:
  `1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a` /
  `c2502bd1865eb323a3ee6337c14be9043167382215aa8fb29cb4ea020978545c` /
  `baf1b2fa6310e7bbe7a5429abe8a0c6dc3acbb97d45fa5d788977d068ac0e2cb` /
  `baaf46a447744c5acbb68708fcc5c19130f98e564a808e9617f08ae340b512dc`.
  The exact inventory is 28 payload files, 24 CSVs, 171,401,140 bytes, and
  1,645,056 rows.
- Frozen WU mirror inventory SHA-256:
  `74a291ee764dccc54ca410f3e9d4e271cc7a6a678c7ab351cc6865ad6e270a5d`.
- Old run inventory SHA-256:
  `0b0798b78b90204ba3447cacf7012f6e5bc99fe4719debe85667b054b1e2cd77`;
  spent attempt file/self SHA-256:
  `e8a3e19da0798fef56c74bca98c6fec798d3d3f99dd253f0c600532c8cc217d3` /
  `55d7dfe0dd9fe45ecd0926931dfcca4376765ccec1751c0036053efcafc9d86b`.
- Original spec file/self SHA-256:
  `cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f` /
  `5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9`.
- Completion spec file/self SHA-256:
  `d540a5dc43845f87e811aca7670e86f5eada3f5ba8476dd1bdc2aef80bd3518c` /
  `6f02e1dcc077c69037017137725931e94d4fd652da976affda12a2109bb67407`.
- Gap manifest file/self SHA-256:
  `6ba020575e3ef1eb903ae0010510caea20f31b31bdf3451c0e03f11175c3de94` /
  `64176a727907c8f62c496f6fb1893c1f7462cfef15c1db3f06ef7b3e244f0ce8`.
- Protected export manifest-file/manifest-self/payload SHA-256:
  `849d7f1241451acfa0d5558d1978a99281c17ea214953b0008d534586190c8d5` /
  `a500d1d0159cc112279a7d94bbe01a22306c741161b15ec98eb9b98556267aaf` /
  `3cef2fe7553cfd0450e78e7c45deda2d186beb607f34318ead545ce5e3863860`.
- Portable validation file/self SHA-256:
  `92cfd27c7ada4b11cd41141cb0544cc29aa0064e7dcff43fd59691f8c2d84492` /
  `747fbc570085cfc26b4de2743c2f16ef802e1dc9fe55701c61cde4668a289d43`.
- Portable export ACL SDDL SHA-256:
  `81fc4c7e398a1d90d2e3903f8e3c38e01ac4263a1d9d21f861a6dc981abfe14e`.
  The explicit non-inherited `CodexSandboxOffline` deny remained present with
  inheritable delete-subtree, write, and delete rights.

The amendment contains every per-file corpus, mirror, and old-run byte count and
SHA-256. Those immutable inventories were revalidated before and after outcome
access; the aggregates above are their canonical inventory hashes.

## Zero-refit, result, and deterministic reproduction proof

Both exact model hashes matched before and after evaluation. Runtime guards
made `HistGradientBoostingRegressor.fit` unavailable during prediction.
`fit_calls_attempted`, refits, partial fits, probability-model refits, and model
writes were all zero. Per model, the pre cohort made 1,388 predictions and the
post cohort made 240. No feature, estimator, lead, threshold, bootstrap method,
seed, unit rule, or decision rule changed.

| Artifact | Bytes | File SHA-256 | Self/canonical SHA-256 |
| :--- | ---: | :--- | :--- |
| `external-completion-attempt.json` | 2,402 | `d5b319917013c4e8d47b5b09e45abf906e7b38f4b7a0e5512a5f19997cd4c81f` | `c25947088569a7619a760c2e80dfb8c49240e5a490cf84a8d18cc3f3ac639faf` |
| `pre-boundary-records.csv` | 153,383 | `06558f061208b6639117308534e80f8916edf7b05d8b9f1fc7fcd50e4831150b` | record rows `76333eed56009b6e00dbb11d4fa495161f52e3797cc3c072b08753f089a73553` |
| `post-boundary-directional-records.csv` | 28,390 | `0a5f921d12078a411c5d388196206db0ac768b7af7bd14a10c70a517257f7089` | record rows `431f2da80097135a5f5354097fbcd38ae576556d6a84e42eb6afbb4ae06b29a0` |
| `result.json` | 97,040 | `7b83e8d2a3b3828ce23414a7feda50f01e4c359a244289d0024c3d83bacb7cf4` | `b5395ca59f15c0f4059cb46336ff2f5d12b1585bd129b3952e5fa94e56c76117` |
| `result-verification.json` | 1,409 | `9aec632de59d1a1d903af4849cb76ef308d76e035f57e3e509d147b7d2543144` | `e438ac528463c7ac180f87611f62c437d22ffb4b674cc4ed372ccc6fcf00cdac` |

The verifier reopened zero outcome files and loaded zero models. From the two
sealed record CSVs it reproduced the pre/post evaluation canonical hashes
`727b51690abc23198fcaff916e76a8f99ddd43932b7a44d0b8a516bb1d6ac929`
and `1408d415032d7ac21252d63dcd224c236d4d5276624afdd4b247f1f19f02c979`,
the union hash
`1653b6f7fb2c5269475223a9722873fe5fc3fd18fb1fdf2044478bb284e23b59`,
and `EXTERNAL_DIRECTION_CONSISTENT`.

The prior-input audit SHA-256 was
`5ab7a914fcf3368c2ba7a6de4de16b0273e37a98b08eea582c889f79a14ad7ce`
both before and after evaluation. The outcome-contract audit SHA-256 was
`dcd192db032f93fd01bbd6d8698d0b30c26c7f897610c3e23d5a64ed976bf0bc`
both before and after. Corpus, export, models, old run, mirror, old evaluator,
old amendment, and ACL state were unchanged; frozen-input writes were zero.

## Serial workstation verification

Every evaluation, replay, test, compile, audit, and roadmap command ran serially
through `scripts/ops/workstation_heavy.ps1` and its host-global mutex.

| Gate | Result |
| :--- | :--- |
| P0 exact Git, source-receipt/bundle, host/principal, mutex, poison, reserved-window, corpus, model, old-run, mirror, export, ACL, key-accounting, and outcome-blind hashes | PASS |
| Pre-outcome focused implementation/schema/wrapper tests | PASS: 56 passed, 15 skipped |
| Pre-outcome compileall for `app`, `src`, `tests` | PASS |
| Introduced host-hook parity repair proof plus cached failure separation | PASS: 17 passed, 367 deselected |
| Final-commit complete workstation suite | Executed once at `8741047c`: 4,454 passed, 18 skipped, 13 warnings, 866 subtests passed, 12 failed in 502.66 seconds |
| Complete-suite failure separation | PASS: all 12 failures were existing `tests/operations/test_experiment_executor.py` cases hitting Windows legacy path length while writing a deeply nested temporary result; the branch changes neither that module nor its tests; the exact cached 12 passed under fresh `C:\t\f100h` in 3.91 seconds |
| One create-only evaluation attempt | PASS: `EXTERNAL_SECONDARY_2026_COMPLETION_COMPLETE` |
| Independent deterministic record-only verification | PASS |
| Post-result owner/schema/import/isolation batch | PASS: 113 passed, 15 skipped in 13.33 seconds |
| Post-result compileall | PASS |
| Agent document audit | PASS: 18 agent files, 842 Markdown files |
| Roadmap generation, lint, and committed-output check | PASS |
| `git diff --check` | PASS for the final report/receipt/generated-roadmap diff |

The first complete run at the initial implementation commit exposed 17 cached
failures: one introduced wrapper/hook allowlist mismatch and 16 unrelated temp
path length/casing failures. The required one-line repository host-hook parity
repair was committed separately. All 17 then passed together under a fresh
short temp root. The complete suite ran once at the resulting final
implementation commit. Its 12 failures are the same existing experiment-executor
path-limit condition; all 12 passed in the bounded short-root reproduction.
No calibration failure remained.

Key commands, with argument arrays encoded canonically for the wrapper, were:

- `-m pytest -q --basetemp=C:\t\w100h-full-final-20260904`
- `-m pytest --lf -q --tb=short --basetemp=C:\t\f100h`
- `-m weather.calibration.multiyear_nwp_residual_external_completion evaluate ...`
- `-m weather.calibration.multiyear_nwp_residual_external_completion verify-result ...`
- `-m pytest -q --basetemp=C:\t\p100h` with the focused owner/schema/import/isolation files
- `-m compileall -q app src tests`
- `-m weather.operations.agent_docs_audit`
- `-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`
- `-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check`
- `scripts\ops\roll_verdict.ps1 -Branch codex/workstation-multiyear-nwp-residual-external-completion-2026-09-100h`

## Changed paths and canonical roll evidence

The source-to-final path set consists of:

1. `.codex/hooks/pre_tool_use_host_load.py`
2. `docs/roadmap/active-backlog.md` (generated timestamp only)
3. `docs/roadmap/agent-report-2026-09-04-workstation-multiyear-nwp-residual-external-completion.md`
4. `docs/roadmap/multiyear-nwp-residual-external-completion-amendment-2026-09-100h.json`
5. `docs/roadmap/workstation-handback-2026-09-04-multiyear-nwp-residual-external-completion.json`
6. `scripts/ops/workload_admission.ps1`
7. `src/weather/calibration/multiyear_nwp_residual_external_completion.py`
8. `src/weather/schema_registry_recent_data.py`
9. `tests/calibration/test_multiyear_nwp_residual_external_completion.py`

The canonical roll tool covered that exact branch and returned exit 1:
`UNDECIDABLE: no live closure evidence`. It named these missing files:

- `data\snapshots\loop_supervisor_status.json`
- `data\snapshots\clob_loop_supervisor_status.json`
- `data\snapshots\observation_trigger_supervisor_status.json`
- `data\snapshots\clob_enrichment_status.json`

Consequently, canonical per-file closure evidence is unavailable for every
changed path above. No file was given a hand-derived roll classification.
Production integration must rerun the same tool where current live closure
evidence exists.

## Prohibited-action and authority audit

The sealed result records zero 2025 outcome accesses; zero model, probability
model, fit, partial-fit, or model-write actions; zero frozen-input writes; zero
imputed low-support rows; zero markets dropped; zero cross-boundary pooled
evaluations; zero provider, market-data, production, Scheduler, exchange, or
credential calls; zero release, distribution, promotion, candidate, alpha,
confirmation, serving, or live actions; and zero branch merges or history
rewrites. The spent prior attempt, prior evaluator and amendment, corpus,
protected export, old run, frozen mirror, and models were not changed.

No reserved date was read because `NONE ARE CURRENTLY RESERVED`. The result root
was absent before the sole create-only attempt and was never retried. No
probabilities were generated and no market prices were read, so this evidence
makes no claim of edge over market prices.

## Immutable handback

The implementation commits are separate from the final report/receipt commit.
The tracked generic receipt records the exact implementation tip/tree, sealed
result identities, verification proof, suite separation, changed paths, and
zero-action audit. Its final tip/tree/bundle fields remain null to avoid a
circular self-binding; the verified bundle hash and its final ref are recorded
outside the commit after the report/receipt commit is created. A normal
noninteractive push is attempted only after local bundle verification, as the
mission directs.
