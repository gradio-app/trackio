import trackio


trackio.init(project="trace-demo-basic")

trackio.log(
    {
        "trace": trackio.Trace(
            messages=[
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "What is 2 + 2?"},
                {"role": "assistant", "content": "2 + 2 = 4."},
            ],
            metadata={"model_version": "demo-v1"},
        )
    }
)

trackio.finish()
