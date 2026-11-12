# Where Scaling Exponents Come From: Deriving Neural Scaling Laws from the Statistics of Language
### Podcast script — an explainer of a 2026 theory paper that predicts how fast language models improve with more data

**Citation:** Cagnetta, Francesco, Allan Raventós, Surya Ganguli, and Matthieu Wyart. "Deriving Neural Scaling Laws from the Statistics of Natural Language." arXiv:2602.07488v2, February 2026. Presented at ICML 2026 (Proceedings of Machine Learning Research, volume 306). This script is based on a detailed summary of the full paper text, not a line-by-line reading; figures were not examined.
**Link:** https://arxiv.org/abs/2602.07488

---

**INTRO**

Anyone who follows language models has seen the plots: test loss falls as a power law in the amount of training data. Double the data, and the loss drops by a fixed factor. These scaling laws drive billion-dollar investment decisions, yet the exponent, the slope of that line on a log-log plot, has been a purely empirical number. You measure it; you don't predict it. This paper claims to predict it. The authors argue that the exponent is fixed by two measurable statistics of the text itself, and they give a formula with no free parameters. The argument is short, and it is the kind of scaling argument a physicist would make, so let's walk through it.

**MAIN CONTENT**

Start with the setting. A language model is trained on P tokens of text to predict the next token, and we measure its cross-entropy loss. With infinite data and infinite context, the best possible loss is the entropy rate of the language, which the paper calls H infinity. The quantity of interest is the excess loss above that floor, and the claim is that it decays as P to the power minus alpha. The goal is to derive alpha.

The first ingredient is how fast correlations in text decay. Take two tokens separated by n positions, and form their covariance matrix: how much knowing one token shifts the probabilities of the other. As matrices go, the natural measure of its size is the operator norm, the largest singular value. The authors measure that this norm decays as a power law in the separation: n to the power minus beta. Tokens that are close are strongly related, tokens that are far apart are weakly related, and the falloff has no characteristic length scale.

The second ingredient is how much context helps. Let H sub n be the conditional entropy of the next token given the previous n tokens. More context can only reduce uncertainty, so H sub n decreases toward H infinity. The authors measure that the gap closes as a power law too: n to the power minus gamma. So gamma tells you the value of information at distance n, and beta tells you the strength of the statistical signal at distance n.

Now the key step, which is a signal-to-noise argument. With P training tokens, any correlation you estimate from data carries sampling noise of order one over the square root of P. That is the usual central limit scaling. A correlation at separation n has strength n to the minus beta. So the model can only detect, and therefore only use, correlations out to the distance where signal equals noise. Set n to the minus beta equal to P to the minus one half, and solve. The result is that the usable context grows as P to the power one over two beta. The authors call this the data-dependent prediction horizon. With more data, the model can see further back, but only polynomially further.

The last step combines the two. If the model makes full use of everything inside its horizon and nothing beyond it, its loss is roughly the conditional entropy at the horizon. The excess over the floor is the horizon to the power minus gamma. Substitute the horizon, P to the one over two beta, and you get P to the power minus gamma over two beta. So the exponent alpha equals gamma divided by twice beta. That is the whole formula: one exponent from entropy, one from correlations, and a factor of two from the central limit theorem.

There is an assumption hidden in that last step: the model must learn what is inside the horizon quickly, so that those errors are not the bottleneck. The paper states this carefully. In general, the exponent is the smaller of two numbers: gamma over two beta, and a second exponent, delta, which describes how fast within-horizon errors shrink. The authors call the case where the horizon dominates the horizon-limited regime, and they argue that deep networks with modern optimizers live there. They expect shallow networks, kernel methods, and n-gram models to fall outside it, because those suffer the curse of dimensionality as the context grows. That part is argued from prior work on synthetic grammars, not tested directly on language here.

Now the evidence. They use two datasets: TinyStories, which is simple synthetic children's stories, and WikiText one hundred three, which is Wikipedia articles. On TinyStories they measure gamma of about point three four and beta of about point eight eight, which predicts an exponent of about point one nine. On WikiText, gamma is about point two seven and beta about point nine four, giving about point one four. They then train transformers from scratch at many dataset sizes: GPT-2 style models of roughly one hundred million to six hundred million parameters, and reduced versions of a Llama architecture, with context lengths from sixty-four to five hundred twelve tokens. The reported result is that the measured learning curves follow the predicted slopes, most clearly at the longer context lengths, and that the same exponents appear across architectures.

There is a second, sharper test. The theory says that the loss restricted to contexts of length n should follow a single master curve once you rescale: divide the dataset size by n to the two beta, and multiply the loss by n to the gamma. Curves for different n should then collapse onto each other. Scaling collapse is a classic check from statistical physics, and it is harder to pass by coincidence than matching a single slope.

Notice what the result implies. The exponent belongs to the data, not the model. Architectures in the same class share the exponent and differ only in the constant in front. The authors use the physics term for this: a universality class. It also means small exponents are a property of language. An exponent of point one five means ten times more data cuts the excess loss by only about thirty percent.

Now the cautions, most of which the authors state themselves. First, scale. At their largest dataset, the horizon is only a few tens of tokens, so the theory is tested at the level of a few sentences. Whether it holds for trillion-token datasets and contexts of a hundred thousand tokens is untested. Second, the power laws are empirical hypotheses, and they are not clean everywhere: the WikiText correlations show a broken power law, and the authors fit only the short-range part. Third, the conditional entropies are estimated from model losses, which are upper bounds, so gamma is itself measured with the help of trained models. Fourth, the argument is a scaling argument, not a theorem. And it covers only the data-limited regime, not the question of how loss scales with model size or compute.

**CLOSING**

Three takeaways. First, the paper proposes that the data scaling exponent of a language model is gamma over two beta: the rate at which context reduces entropy, divided by twice the rate at which token correlations decay. Second, the mechanism is a prediction horizon: more data lets the model resolve weaker, longer-range correlations, and the loss tracks the entropy at that horizon. Third, the evidence is consistent across architectures but limited to academic scale. The open questions are whether the same law holds at frontier scale, and whether an architecture or a kind of data could change the universality class and so the exponent itself.

---

*Source: Cagnetta, Raventós, Ganguli, and Wyart, "Deriving Neural Scaling Laws from the Statistics of Natural Language," arXiv:2602.07488, ICML 2026.*
