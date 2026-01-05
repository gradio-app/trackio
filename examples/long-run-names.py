import random

import trackio as wandb

EPOCHS = 20
PROJECT_ID = random.randint(100000, 999999)

for run in range(10):
    wandb.init(
        project=f"long-names-{PROJECT_ID}",
        name=f"{run}-very-long-descriptive-words-and-details",
        config=dict(
            epochs=EPOCHS,
            learning_rate=0.001,
            batch_size=32,
            max_position_embeddings=32768,
            hidden_size=896,
            intermediate_size=4864,
            num_attention_heads=24,
            weight_decay_regularization_coefficient=0.0001,
            momentum_coefficient_for_optimizer_update=0.9,
            dropout_probability_used_during_training=0.1,
            attention_dropout_probability_in_transformer_layers=0.1,
            hidden_dropout_probability_in_feedforward_network=0.1,
            layer_norm_epsilon_parameter_for_numerical_stability=1e-12,
            max_gradient_norm_for_clipping_during_backpropagation=1.0,
            warmup_steps_in_learning_rate_schedule=1000,
            total_training_steps_planned_for_this_experiment=10000,
            activation_function_used_in_hidden_layers="gelu",
            initialization_method_for_weight_matrices="xavier_uniform",
            optimizer_type_used_for_parameter_updates="adamw",
            beta1_parameter_for_adam_optimizer_momentum=0.9,
            beta2_parameter_for_adam_optimizer_variance=0.999,
            epsilon_value_for_adam_optimizer_numerical_stability=1e-8,
        ),
    )

    for epoch in range(EPOCHS):
        wandb.log({"train/loss": 2.5 - epoch * 0.1})

wandb.finish()
