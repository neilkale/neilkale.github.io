---
title: "Dynamical systems approaches for deep learning"
excerpt: "My undergraduate senior thesis from 2024 reimagines neural network designs as discrete dynamical systems, and investigates the effects of sparse and low-rank matrices on iterative network performance. <br/><img src='/images/portfolio_inn.png'>"
collection: portfolio
---

Summary
-----
Under the supervision of Professor Randy Paffenroth, my senior thesis explores iterative neural networks (INNs), which reimagine neural network designs as iterated functions, and the recently introduced Sequential2D framework for neural networks that frames INN functions as left matrix multiplications for enhanced computational efficiency. We investigate the effects of sparse and low-rank matrix approximations on model performance, particularly focusing on sparsity and weight distribution using the MNIST Random Anomaly Task.

Our results highlight the delicate balance between parallelization advantages and the need for equitable weight distribution. The comparison of sparse, low rank, and dense matrices reveals low-rank matrices’ role in boosting computational speed without drastically affecting model accuracy. Overall, this research advances our understanding of INNs and Sequential2D, underlining the significance of matrix representation methods in fine-tuning neural network architectures for improved performance and efficiency.

<img src='/images/portfolio_inn.png'>

Figure. A two-layer multilayer perceptron (MLP) represented as a 3x3 iterative neural network.
