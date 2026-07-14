# 高价值混合来源真实抓取轮次证据

> 验收日期：2026-07-14。每个目标每轮最多抓取 5 条。所有记录来自本机 PostgreSQL。

## 验收结论

- 固定波次：45 个目标，9 个来源组。
- 实际执行 4 轮：前两轮有旧主分支 Worker 抢占少量新目标并产生 `unknown_source`；停止旧 Worker 后追加第 4 轮，保留原始失败记录而不覆盖。
- 当前健康投影：35 个已有内容的直接抓取、5 个间接发现、1 个入口可用但暂无内容样本、3 个 Reddit 凭据阻塞、1 个 GDELT 降级、41 个目标最近三次 FetchRun 稳定。
- Reddit 未配置 OAuth，三者均按预期返回阻塞；未回退登录网页或 Cookie 抓取。
- GDELT 在连续请求中出现 `rate_limited/fetch_failed`，因此保持 `degraded` 且不启用常规抓取。

## 轮次汇总

| 轮次 | Operation ID | 开始时间（UTC） | 结束时间（UTC） | 操作终态 |
|---:|---|---|---|---|
| 1 | 540–584 | 2026-07-14T09:44:20.657070+00:00 | 2026-07-14T09:45:43.707639+00:00 | failed 5、partial 4、succeeded 36 |
| 2 | 585–629 | 2026-07-14T09:46:14.371964+00:00 | 2026-07-14T09:47:15.087567+00:00 | failed 1、partial 4、succeeded 40 |
| 3 | 630–674 | 2026-07-14T09:47:43.710780+00:00 | 2026-07-14T09:48:52.945963+00:00 | failed 1、partial 3、succeeded 41 |
| 4 | 675–719 | 2026-07-14T09:49:06.307919+00:00 | 2026-07-14T09:49:52.070599+00:00 | partial 3、succeeded 42 |

## 第 1 轮明细

| Operation | 目标 | FetchRun 终态 | 收到条目 | 错误码 | 完成时间（UTC） |
|---:|---|---|---:|---|---|
| 540 | `universe-bloomberg-2` | succeeded | 5 | — | 2026-07-14T09:44:22.377314+00:00 |
| 541 | `huggingface-youtube` | succeeded | 5 | — | 2026-07-14T09:44:22.547310+00:00 |
| 542 | `universe-ap-2` | succeeded | 5 | — | 2026-07-14T09:44:22.373734+00:00 |
| 543 | `nvidia-developer-youtube` | succeeded | 5 | — | 2026-07-14T09:44:22.748047+00:00 |
| 544 | `reddit-localllama` | blocked | 0 | permission_required | 2026-07-14T09:44:21.718305+00:00 |
| 545 | `mastodon-llm-tag` | 未创建 FetchRun | 0 | unknown_source | 2026-07-14T09:44:21.749089+00:00 |
| 546 | `hackernews-best` | succeeded | 5 | — | 2026-07-14T09:44:24.095142+00:00 |
| 547 | `google-news-business` | succeeded | 5 | — | 2026-07-14T09:44:24.014907+00:00 |
| 548 | `universe-techcrunch-1` | succeeded | 5 | — | 2026-07-14T09:44:23.335595+00:00 |
| 549 | `mastodon-artificialintelligence-tag` | 未创建 FetchRun | 0 | unknown_source | 2026-07-14T09:44:22.757935+00:00 |
| 550 | `universe-mit-tech-review-1` | succeeded | 5 | — | 2026-07-14T09:44:23.807677+00:00 |
| 551 | `google-news-policy-safety` | succeeded | 5 | — | 2026-07-14T09:44:24.885103+00:00 |
| 552 | `universe-cnbc-1` | succeeded | 5 | — | 2026-07-14T09:44:24.643649+00:00 |
| 553 | `hackernews-new` | succeeded | 5 | — | 2026-07-14T09:44:25.626297+00:00 |
| 554 | `universe-wsj-2` | succeeded | 5 | — | 2026-07-14T09:44:25.193648+00:00 |
| 555 | `universe-the-verge-1` | succeeded | 5 | — | 2026-07-14T09:44:24.958680+00:00 |
| 556 | `universe-financial-times-2` | 未创建 FetchRun | 0 | hard_blocked | 2026-07-14T09:44:24.806630+00:00 |
| 557 | `mastodon-ai-tag` | 未创建 FetchRun | 0 | unknown_source | 2026-07-14T09:44:24.815258+00:00 |
| 558 | `reddit-artificial` | blocked | 0 | permission_required | 2026-07-14T09:44:25.660997+00:00 |
| 559 | `hackernews-top` | succeeded | 5 | — | 2026-07-14T09:44:26.772975+00:00 |
| 560 | `no-priors-youtube` | succeeded | 5 | — | 2026-07-14T09:44:26.879174+00:00 |
| 561 | `google-deepmind-youtube` | succeeded | 5 | — | 2026-07-14T09:44:27.167117+00:00 |
| 562 | `universe-guardian-1` | succeeded | 5 | — | 2026-07-14T09:44:27.124916+00:00 |
| 563 | `anthropic-youtube` | 未创建 FetchRun | 0 | unknown_source | 2026-07-14T09:44:25.826353+00:00 |
| 564 | `universe-bbc-1` | succeeded | 5 | — | 2026-07-14T09:44:27.657057+00:00 |
| 565 | `techmeme-feed` | succeeded | 5 | — | 2026-07-14T09:44:27.977296+00:00 |
| 566 | `huggingface-bluesky` | succeeded | 4 | — | 2026-07-14T09:44:27.630369+00:00 |
| 567 | `simon-willison-bluesky` | succeeded | 5 | — | 2026-07-14T09:44:28.262906+00:00 |
| 568 | `reddit-machinelearning` | blocked | 0 | permission_required | 2026-07-14T09:44:28.105209+00:00 |
| 569 | `mastodon-machinelearning-tag` | succeeded | 5 | — | 2026-07-14T09:44:29.152139+00:00 |
| 570 | `cognitive-revolution-youtube` | succeeded | 5 | — | 2026-07-14T09:44:29.510618+00:00 |
| 571 | `gdelt-ai` | failed（3 次尝试） | 0 | fetch_failed | 2026-07-14T09:45:43.691825+00:00 |
| 572 | `google-news-chips-compute` | succeeded | 5 | — | 2026-07-14T09:44:29.698387+00:00 |
| 573 | `the-verge-bluesky` | succeeded | 5 | — | 2026-07-14T09:44:29.404624+00:00 |
| 574 | `google-news-research` | succeeded | 5 | — | 2026-07-14T09:44:30.662773+00:00 |
| 575 | `universe-ars-technica-1` | no_change | 0 | — | 2026-07-14T09:44:30.116918+00:00 |
| 576 | `universe-reuters-2` | succeeded | 5 | — | 2026-07-14T09:44:31.022561+00:00 |
| 577 | `universe-wired-1` | succeeded | 5 | — | 2026-07-14T09:44:30.748484+00:00 |
| 578 | `anthropic-bluesky` | succeeded | 0 | — | 2026-07-14T09:44:30.763346+00:00 |
| 579 | `latent-space-youtube` | succeeded | 5 | — | 2026-07-14T09:44:32.509202+00:00 |
| 580 | `mit-tech-review-bluesky` | succeeded | 5 | — | 2026-07-14T09:44:32.375859+00:00 |
| 581 | `universe-venturebeat-1` | succeeded | 5 | — | 2026-07-14T09:44:32.145573+00:00 |
| 582 | `techcrunch-bluesky` | succeeded | 5 | — | 2026-07-14T09:44:32.083961+00:00 |
| 583 | `google-news-ai` | succeeded | 5 | — | 2026-07-14T09:44:33.705595+00:00 |
| 584 | `openai-youtube` | succeeded | 5 | — | 2026-07-14T09:44:33.914564+00:00 |

## 第 2 轮明细

| Operation | 目标 | FetchRun 终态 | 收到条目 | 错误码 | 完成时间（UTC） |
|---:|---|---|---:|---|---|
| 585 | `nvidia-developer-youtube` | succeeded | 5 | — | 2026-07-14T09:46:15.789298+00:00 |
| 586 | `reddit-localllama` | blocked | 0 | permission_required | 2026-07-14T09:46:15.457361+00:00 |
| 587 | `mastodon-artificialintelligence-tag` | succeeded | 5 | — | 2026-07-14T09:46:16.786836+00:00 |
| 588 | `universe-financial-times-2` | succeeded | 5 | — | 2026-07-14T09:46:15.949055+00:00 |
| 589 | `hackernews-new` | succeeded | 5 | — | 2026-07-14T09:46:17.457757+00:00 |
| 590 | `cognitive-revolution-youtube` | succeeded | 5 | — | 2026-07-14T09:46:17.008526+00:00 |
| 591 | `no-priors-youtube` | succeeded | 5 | — | 2026-07-14T09:46:17.153127+00:00 |
| 592 | `mastodon-machinelearning-tag` | succeeded | 5 | — | 2026-07-14T09:46:17.435176+00:00 |
| 593 | `techcrunch-bluesky` | succeeded | 5 | — | 2026-07-14T09:46:17.974276+00:00 |
| 594 | `universe-wired-1` | succeeded | 5 | — | 2026-07-14T09:46:17.706746+00:00 |
| 595 | `huggingface-bluesky` | succeeded | 5 | — | 2026-07-14T09:46:17.948008+00:00 |
| 596 | `universe-bbc-1` | succeeded | 5 | — | 2026-07-14T09:46:18.255296+00:00 |
| 597 | `universe-cnbc-1` | succeeded | 5 | — | 2026-07-14T09:46:18.501059+00:00 |
| 598 | `universe-mit-tech-review-1` | no_change | 0 | — | 2026-07-14T09:46:18.364234+00:00 |
| 599 | `universe-wsj-2` | succeeded | 5 | — | 2026-07-14T09:46:19.058506+00:00 |
| 600 | `the-verge-bluesky` | succeeded | 5 | — | 2026-07-14T09:46:19.011712+00:00 |
| 601 | `universe-ars-technica-1` | succeeded | 5 | — | 2026-07-14T09:46:19.366752+00:00 |
| 602 | `simon-willison-bluesky` | succeeded | 5 | — | 2026-07-14T09:46:19.522048+00:00 |
| 603 | `google-news-research` | 未创建 FetchRun | 0 | unknown_source | 2026-07-14T09:46:18.523089+00:00 |
| 604 | `google-news-ai` | succeeded | 5 | — | 2026-07-14T09:46:20.470264+00:00 |
| 605 | `google-news-policy-safety` | succeeded | 5 | — | 2026-07-14T09:46:20.482960+00:00 |
| 606 | `hackernews-top` | succeeded | 5 | — | 2026-07-14T09:46:20.834296+00:00 |
| 607 | `universe-ap-2` | 未创建 FetchRun | 0 | hard_blocked | 2026-07-14T09:46:19.698410+00:00 |
| 608 | `google-deepmind-youtube` | succeeded | 5 | — | 2026-07-14T09:46:20.910037+00:00 |
| 609 | `reddit-machinelearning` | blocked | 0 | permission_required | 2026-07-14T09:46:20.460543+00:00 |
| 610 | `universe-the-verge-1` | no_change | 0 | — | 2026-07-14T09:46:21.280335+00:00 |
| 611 | `openai-youtube` | succeeded | 5 | — | 2026-07-14T09:46:21.785290+00:00 |
| 612 | `google-news-chips-compute` | succeeded | 5 | — | 2026-07-14T09:46:21.856284+00:00 |
| 613 | `techmeme-feed` | no_change | 0 | — | 2026-07-14T09:46:21.567830+00:00 |
| 614 | `mit-tech-review-bluesky` | succeeded | 5 | — | 2026-07-14T09:46:21.999178+00:00 |
| 615 | `gdelt-ai` | succeeded（2 次尝试） | 5 | — | 2026-07-14T09:47:15.073695+00:00 |
| 616 | `universe-techcrunch-1` | no_change | 0 | — | 2026-07-14T09:46:22.144932+00:00 |
| 617 | `google-news-business` | succeeded | 5 | — | 2026-07-14T09:46:23.167829+00:00 |
| 618 | `universe-guardian-1` | no_change | 0 | — | 2026-07-14T09:46:22.775873+00:00 |
| 619 | `universe-venturebeat-1` | succeeded | 5 | — | 2026-07-14T09:46:23.071062+00:00 |
| 620 | `reddit-artificial` | blocked | 0 | permission_required | 2026-07-14T09:46:22.919386+00:00 |
| 621 | `anthropic-bluesky` | succeeded | 0 | — | 2026-07-14T09:46:23.438253+00:00 |
| 622 | `anthropic-youtube` | succeeded | 5 | — | 2026-07-14T09:46:24.311513+00:00 |
| 623 | `universe-reuters-2` | succeeded | 5 | — | 2026-07-14T09:46:24.208272+00:00 |
| 624 | `universe-bloomberg-2` | succeeded | 5 | — | 2026-07-14T09:46:24.495066+00:00 |
| 625 | `mastodon-llm-tag` | succeeded | 5 | — | 2026-07-14T09:46:24.813953+00:00 |
| 626 | `huggingface-youtube` | succeeded | 5 | — | 2026-07-14T09:46:25.775977+00:00 |
| 627 | `hackernews-best` | succeeded | 5 | — | 2026-07-14T09:46:25.761013+00:00 |
| 628 | `mastodon-ai-tag` | succeeded | 5 | — | 2026-07-14T09:46:25.906946+00:00 |
| 629 | `latent-space-youtube` | succeeded | 5 | — | 2026-07-14T09:46:26.186918+00:00 |

## 第 3 轮明细

| Operation | 目标 | FetchRun 终态 | 收到条目 | 错误码 | 完成时间（UTC） |
|---:|---|---|---:|---|---|
| 630 | `universe-mit-tech-review-1` | no_change | 0 | — | 2026-07-14T09:47:45.238752+00:00 |
| 631 | `universe-bloomberg-2` | succeeded | 5 | — | 2026-07-14T09:47:45.474108+00:00 |
| 632 | `universe-bbc-1` | succeeded | 5 | — | 2026-07-14T09:47:45.430520+00:00 |
| 633 | `huggingface-bluesky` | succeeded | 5 | — | 2026-07-14T09:47:45.366020+00:00 |
| 634 | `anthropic-bluesky` | succeeded | 0 | — | 2026-07-14T09:47:45.882604+00:00 |
| 635 | `universe-financial-times-2` | succeeded | 5 | — | 2026-07-14T09:47:46.191559+00:00 |
| 636 | `nvidia-developer-youtube` | succeeded | 5 | — | 2026-07-14T09:47:46.888750+00:00 |
| 637 | `techcrunch-bluesky` | succeeded | 5 | — | 2026-07-14T09:47:46.693041+00:00 |
| 638 | `universe-venturebeat-1` | succeeded | 5 | — | 2026-07-14T09:47:47.107224+00:00 |
| 639 | `gdelt-ai` | failed（3 次尝试） | 0 | rate_limited | 2026-07-14T09:48:52.920918+00:00 |
| 640 | `reddit-machinelearning` | blocked | 0 | permission_required | 2026-07-14T09:47:47.442867+00:00 |
| 641 | `universe-wired-1` | succeeded | 5 | — | 2026-07-14T09:47:47.867217+00:00 |
| 642 | `mastodon-ai-tag` | succeeded | 5 | — | 2026-07-14T09:47:49.000303+00:00 |
| 643 | `google-news-research` | succeeded | 5 | — | 2026-07-14T09:47:48.670978+00:00 |
| 644 | `universe-ars-technica-1` | no_change | 0 | — | 2026-07-14T09:47:48.845789+00:00 |
| 645 | `google-deepmind-youtube` | succeeded | 5 | — | 2026-07-14T09:47:50.042027+00:00 |
| 646 | `universe-reuters-2` | succeeded | 5 | — | 2026-07-14T09:47:49.606318+00:00 |
| 647 | `mit-tech-review-bluesky` | succeeded | 5 | — | 2026-07-14T09:47:50.192710+00:00 |
| 648 | `no-priors-youtube` | succeeded | 5 | — | 2026-07-14T09:47:50.945957+00:00 |
| 649 | `mastodon-machinelearning-tag` | succeeded | 5 | — | 2026-07-14T09:47:51.671806+00:00 |
| 650 | `mastodon-artificialintelligence-tag` | succeeded | 5 | — | 2026-07-14T09:47:51.518032+00:00 |
| 651 | `universe-guardian-1` | no_change | 0 | — | 2026-07-14T09:47:51.989430+00:00 |
| 652 | `google-news-chips-compute` | succeeded | 5 | — | 2026-07-14T09:47:52.492021+00:00 |
| 653 | `huggingface-youtube` | succeeded | 5 | — | 2026-07-14T09:47:52.937640+00:00 |
| 654 | `latent-space-youtube` | succeeded | 5 | — | 2026-07-14T09:47:53.333039+00:00 |
| 655 | `anthropic-youtube` | succeeded | 5 | — | 2026-07-14T09:47:53.760223+00:00 |
| 656 | `simon-willison-bluesky` | succeeded | 5 | — | 2026-07-14T09:47:54.078366+00:00 |
| 657 | `google-news-ai` | succeeded | 5 | — | 2026-07-14T09:47:54.212625+00:00 |
| 658 | `google-news-policy-safety` | succeeded | 5 | — | 2026-07-14T09:47:54.596727+00:00 |
| 659 | `openai-youtube` | succeeded | 5 | — | 2026-07-14T09:47:55.530294+00:00 |
| 660 | `hackernews-new` | succeeded | 5 | — | 2026-07-14T09:47:55.977905+00:00 |
| 661 | `universe-wsj-2` | succeeded | 5 | — | 2026-07-14T09:47:55.336807+00:00 |
| 662 | `the-verge-bluesky` | succeeded | 5 | — | 2026-07-14T09:47:56.358408+00:00 |
| 663 | `reddit-artificial` | blocked | 0 | permission_required | 2026-07-14T09:47:56.339937+00:00 |
| 664 | `google-news-business` | succeeded | 5 | — | 2026-07-14T09:47:57.055517+00:00 |
| 665 | `reddit-localllama` | blocked | 0 | permission_required | 2026-07-14T09:47:57.120251+00:00 |
| 666 | `universe-cnbc-1` | succeeded | 5 | — | 2026-07-14T09:47:57.202221+00:00 |
| 667 | `universe-techcrunch-1` | no_change | 0 | — | 2026-07-14T09:47:57.692569+00:00 |
| 668 | `hackernews-top` | succeeded | 5 | — | 2026-07-14T09:47:58.740289+00:00 |
| 669 | `hackernews-best` | succeeded | 5 | — | 2026-07-14T09:47:58.885543+00:00 |
| 670 | `cognitive-revolution-youtube` | succeeded | 5 | — | 2026-07-14T09:47:59.594390+00:00 |
| 671 | `techmeme-feed` | no_change | 0 | — | 2026-07-14T09:47:59.449202+00:00 |
| 672 | `universe-ap-2` | succeeded | 5 | — | 2026-07-14T09:47:59.935021+00:00 |
| 673 | `universe-the-verge-1` | no_change | 0 | — | 2026-07-14T09:48:00.175210+00:00 |
| 674 | `mastodon-llm-tag` | succeeded | 5 | — | 2026-07-14T09:48:00.966923+00:00 |

## 第 4 轮明细

| Operation | 目标 | FetchRun 终态 | 收到条目 | 错误码 | 完成时间（UTC） |
|---:|---|---|---:|---|---|
| 675 | `anthropic-youtube` | succeeded | 5 | — | 2026-07-14T09:49:07.687519+00:00 |
| 676 | `universe-ap-2` | succeeded | 5 | — | 2026-07-14T09:49:07.936342+00:00 |
| 677 | `techcrunch-bluesky` | succeeded | 5 | — | 2026-07-14T09:49:07.764745+00:00 |
| 678 | `universe-wsj-2` | succeeded | 5 | — | 2026-07-14T09:49:08.563782+00:00 |
| 679 | `universe-mit-tech-review-1` | no_change | 0 | — | 2026-07-14T09:49:08.362001+00:00 |
| 680 | `anthropic-bluesky` | succeeded | 0 | — | 2026-07-14T09:49:08.465769+00:00 |
| 681 | `universe-techcrunch-1` | no_change | 0 | — | 2026-07-14T09:49:08.615705+00:00 |
| 682 | `universe-bloomberg-2` | succeeded | 5 | — | 2026-07-14T09:49:09.483967+00:00 |
| 683 | `mastodon-artificialintelligence-tag` | succeeded | 5 | — | 2026-07-14T09:49:10.200017+00:00 |
| 684 | `latent-space-youtube` | succeeded | 5 | — | 2026-07-14T09:49:09.926001+00:00 |
| 685 | `mit-tech-review-bluesky` | succeeded | 5 | — | 2026-07-14T09:49:09.712187+00:00 |
| 686 | `universe-guardian-1` | no_change | 0 | — | 2026-07-14T09:49:10.383614+00:00 |
| 687 | `universe-financial-times-2` | succeeded | 5 | — | 2026-07-14T09:49:10.581770+00:00 |
| 688 | `openai-youtube` | succeeded | 5 | — | 2026-07-14T09:49:11.338962+00:00 |
| 689 | `hackernews-new` | succeeded | 5 | — | 2026-07-14T09:49:12.061627+00:00 |
| 690 | `nvidia-developer-youtube` | succeeded | 5 | — | 2026-07-14T09:49:11.882202+00:00 |
| 691 | `google-news-business` | succeeded | 5 | — | 2026-07-14T09:49:11.802358+00:00 |
| 692 | `google-news-policy-safety` | succeeded | 5 | — | 2026-07-14T09:49:12.610505+00:00 |
| 693 | `universe-wired-1` | succeeded | 5 | — | 2026-07-14T09:49:12.556210+00:00 |
| 694 | `no-priors-youtube` | succeeded | 5 | — | 2026-07-14T09:49:13.110848+00:00 |
| 695 | `mastodon-ai-tag` | succeeded | 5 | — | 2026-07-14T09:49:13.326983+00:00 |
| 696 | `google-news-chips-compute` | succeeded | 5 | — | 2026-07-14T09:49:13.791439+00:00 |
| 697 | `gdelt-ai` | succeeded（2 次尝试） | 5 | — | 2026-07-14T09:49:52.061369+00:00 |
| 698 | `hackernews-best` | succeeded | 5 | — | 2026-07-14T09:49:14.738124+00:00 |
| 699 | `google-news-ai` | succeeded | 5 | — | 2026-07-14T09:49:14.591952+00:00 |
| 700 | `universe-venturebeat-1` | succeeded | 5 | — | 2026-07-14T09:49:14.796883+00:00 |
| 701 | `reddit-artificial` | blocked | 0 | permission_required | 2026-07-14T09:49:15.348826+00:00 |
| 702 | `universe-cnbc-1` | succeeded | 5 | — | 2026-07-14T09:49:15.701283+00:00 |
| 703 | `universe-the-verge-1` | no_change | 0 | — | 2026-07-14T09:49:15.805628+00:00 |
| 704 | `simon-willison-bluesky` | succeeded | 5 | — | 2026-07-14T09:49:16.376790+00:00 |
| 705 | `reddit-localllama` | blocked | 0 | permission_required | 2026-07-14T09:49:16.452624+00:00 |
| 706 | `google-news-research` | succeeded | 5 | — | 2026-07-14T09:49:16.917753+00:00 |
| 707 | `techmeme-feed` | no_change | 0 | — | 2026-07-14T09:49:17.089981+00:00 |
| 708 | `google-deepmind-youtube` | succeeded | 5 | — | 2026-07-14T09:49:17.851391+00:00 |
| 709 | `mastodon-machinelearning-tag` | succeeded | 5 | — | 2026-07-14T09:49:18.618666+00:00 |
| 710 | `universe-bbc-1` | succeeded | 5 | — | 2026-07-14T09:49:17.993470+00:00 |
| 711 | `the-verge-bluesky` | succeeded | 5 | — | 2026-07-14T09:49:18.930181+00:00 |
| 712 | `universe-reuters-2` | succeeded | 5 | — | 2026-07-14T09:49:18.985101+00:00 |
| 713 | `hackernews-top` | succeeded | 5 | — | 2026-07-14T09:49:20.238416+00:00 |
| 714 | `huggingface-bluesky` | succeeded | 5 | — | 2026-07-14T09:49:19.701351+00:00 |
| 715 | `huggingface-youtube` | succeeded | 5 | — | 2026-07-14T09:49:20.269951+00:00 |
| 716 | `mastodon-llm-tag` | succeeded | 5 | — | 2026-07-14T09:49:21.112793+00:00 |
| 717 | `universe-ars-technica-1` | no_change | 0 | — | 2026-07-14T09:49:20.867143+00:00 |
| 718 | `reddit-machinelearning` | blocked | 0 | permission_required | 2026-07-14T09:49:21.060586+00:00 |
| 719 | `cognitive-revolution-youtube` | succeeded | 5 | — | 2026-07-14T09:49:22.254593+00:00 |
