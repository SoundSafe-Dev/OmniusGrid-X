# Gemma 4 Training Instructions: Correlation AI Fine-Tuning

## Dataset Information

- **Total Scenarios**: 499,986
- **Domain Coverage**: 47 operational domains (10,638 scenarios per domain)
- **Single/Multi-Domain Ratio**: 50/50 split
- **Severity Distribution**: Critical (20.1%), High (26.6%), Medium (26.6%), Low (26.7%)
- **Dataset Split**: 80% train (399,988), 10% validation (49,998), 10% test (50,000)
- **Format**: JSONL with system prompts, user inputs (DATA INGEST), and model outputs

## Dataset Location

```
backend/dataset/training_data.jsonl  # Full dataset (499,986 scenarios)
backend/dataset/train.jsonl          # Training set (399,988 scenarios)
backend/dataset/validation.jsonl     # Validation set (49,998 scenarios)
backend/dataset/test.jsonl            # Test set (50,000 scenarios)
```

---

## Step 1: Install Dependencies

```bash
pip install torch>=2.0.0
pip install transformers>=4.35.0
pip install datasets>=2.14.0
pip install peft>=0.6.0
pip install accelerate>=0.24.0
pip install wandb>=0.15.0
pip install deepspeed>=0.10.0
```

---

## Step 2: Prepare Dataset

```bash
cd backend

# Verify dataset integrity
python scripts/verify_dataset.py dataset/training_data.jsonl

# Format for Gemma 4 chat format
python scripts/format_for_gemma4.py \
  --input dataset/train.jsonl \
  --output dataset/train_gemma4.jsonl \
  --format chat

python scripts/format_for_gemma4.py \
  --input dataset/validation.jsonl \
  --output dataset/validation_gemma4.jsonl \
  --format chat

python scripts/format_for_gemma4.py \
  --input dataset/test.jsonl \
  --output dataset/test_gemma4.jsonl \
  --format chat
```

---

## Step 3: Configure LoRA Fine-Tuning

Create `configs/lora_config.json`:

```json
{
  "r": 64,
  "lora_alpha": 128,
  "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
  "lora_dropout": 0.05,
  "bias": "none",
  "task_type": "CAUSAL_LM"
}
```

---

## Step 4: Start LoRA Training

```bash
accelerate launch scripts/train_lora.py \
  --model-name google/gemma-4-9b-it \
  --train-file dataset/train_gemma4.jsonl \
  --validation-file dataset/validation_gemma4.jsonl \
  --output-dir checkpoints/lora \
  --config configs/lora_config.json \
  --num-train-epochs 3 \
  --per-device-train-batch-size 8 \
  --per-device-eval-batch-size 8 \
  --gradient-accumulation-steps 4 \
  --learning-rate 5e-5 \
  --warmup-steps 500 \
  --logging-steps 100 \
  --save-steps 1000 \
  --eval-steps 1000 \
  --fp16 \
  --gradient-checkpointing \
  --report-to wandb \
  --run-name gemma4-correlation-ai-lora
```

---

## Step 5: Select Best LoRA Checkpoint

```bash
python scripts/select_best_checkpoint.py \
  --checkpoint-dir checkpoints/lora \
  --metric validation_loss \
  --output checkpoints/best_lora
```

---

## Step 6: Configure DeepSpeed for Full Fine-Tuning

Create `configs/deepspeed_config.json`:

```json
{
  "zero_optimization": {
    "stage": 3,
    "offload_optimizer": {
      "device": "cpu"
    },
    "offload_param": {
      "device": "cpu"
    }
  },
  "gradient_accumulation_steps": "auto",
  "gradient_clipping": "auto",
  "steps_per_print": 100
}
```

---

## Step 7: Start Full Fine-Tuning

```bash
deepspeed --num_gpus=4 scripts/train_full.py \
  --model-name google/gemma-4-9b-it \
  --train-file dataset/train_gemma4.jsonl \
  --validation-file dataset/validation_gemma4.jsonl \
  --output-dir checkpoints/full \
  --deepspeed configs/deepspeed_config.json \
  --num-train-epochs 2 \
  --per-device-train-batch-size 4 \
  --per-device-eval-batch-size 4 \
  --gradient-accumulation-steps 8 \
  --learning-rate 1e-5 \
  --warmup-ratio 0.03 \
  --logging-steps 50 \
  --save-steps 500 \
  --eval-steps 500 \
  --fp16 \
  --gradient-checkpointing \
  --report-to wandb \
  --run-name gemma4-correlation-ai-full
```

---

## Step 8: Merge LoRA Weights

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM

base_model = AutoModelForCausalLM.from_pretrained("google/gemma-4-9b-it")
model = PeftModel.from_pretrained(base_model, "checkpoints/best_lora")
model = model.merge_and_unload()
model.save_pretrained("checkpoints/merged_model")
```

---

## Step 9: Evaluate Fine-Tuned Model

```bash
python scripts/evaluate_model.py \
  --model checkpoints/best_full \
  --test-file dataset/test_gemma4.jsonl \
  --output results/final_evaluation.json
```

Metrics to track:
- Exact Match Accuracy
- Risk Score Correlation
- Domain Detection F1
- Actionable Output Rate
- Cross-Domain Accuracy
- Critical Severity Detection

---

## Step 10: Quantize Model for Deployment

```python
from transformers import BitsAndBytesConfig, AutoModelForCausalLM

quantization_config = BitsAndBytesConfig(
    load_in_8bit=True,
    bnb_8bit_compute_dtype=torch.bfloat16
)

model = AutoModelForCausalLM.from_pretrained(
    "checkpoints/best_full",
    quantization_config=quantization_config
)
model.save_pretrained("models/gemma4_correlation_ai_quantized")
```

---

## Step 11: Update Correlation AI Engine

Update `backend/app/services/correlation_ai_engine.py`:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

class CorrelationAIEngine:
    def __init__(self):
        self.model = AutoModelForCausalLM.from_pretrained(
            "models/gemma4_correlation_ai_quantized",
            device_map="auto",
            quantization_config=BitsAndBytesConfig(load_in_8bit=True)
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            "models/gemma4_correlation_ai_quantized"
        )
```

---

## Step 12: Test Integration

```bash
# Start backend server
cd backend
uvicorn app.main:app --reload

# Test correlation AI endpoint
curl -X POST http://localhost:8000/api/v1/nlp/correlation/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze production delays on Cell-H"}'
```

---

## Troubleshooting

**Out of Memory (OOM)**
- Reduce batch size
- Enable gradient checkpointing (already included)
- Use DeepSpeed ZeRO-3 (already configured)

**Training Loss Not Decreasing**
- Lower learning rate (try 1e-5 or 5e-6)
- Verify data quality
- Increase warmup steps

**Overfitting**
- Increase weight decay
- Reduce number of epochs
- Add dropout to LoRA config

**Slow Training**
- Increase batch size if memory allows
- Use mixed precision (fp16 already enabled)
- Increase gradient accumulation steps

---

## Resources

- **Gemma 4 Documentation**: https://ai.google.dev/gemma
- **Hugging Face Transformers**: https://huggingface.co/docs/transformers
- **PEFT (LoRA)**: https://huggingface.co/docs/peft
- **DeepSpeed**: https://www.deepspeed.ai/
- **Weights & Biases**: https://wandb.ai/
