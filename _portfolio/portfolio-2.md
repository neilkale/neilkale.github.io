---
title: "Dynamical systems approaches for deep learning"
excerpt: "My undergraduate senior thesis (2023) develops a novel framework for designing neural networks as iterative matrix multiplications. <br/><img src='/images/portfolio_inn.png'>"
collection: portfolio
---

Summary
-----
Under the supervision of Professor Randy Paffenroth, my senior thesis explores a new framework for deep learning rooted in dynamical systems theory. These 'iterative neural networks' (INNs) transform opaque architectures, such as LSTMs and transformers, into simple iterative matrix multiplications. The resulting models are mathematically equivalent, but more interpretable and easier to finetune.

My goal is to prove that, in many cases, these matrix models can be uniquely finetuned to train faster than layered models and achieve better accuracy with fewer parameters. Currently, I am reworking the Simple Recurrent Unit (Lei et al., 2017) into an INN with the eventual goal of significantly improving the model's performance through careful finetuning.

<img src='/images/portfolio_inn.png'>

Figure. A two-layer multilayer perceptron (MLP) represented as a 3x3 iterative neural network. The SRU model is represented by a much sparser 14x14 INN.
