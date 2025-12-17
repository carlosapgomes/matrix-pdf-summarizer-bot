# Dual-LLM Configuration Guide

## Overview

This guide provides detailed configuration examples and explanations for setting up the dual-LLM feature. It covers various deployment scenarios, from simple single-LLM setups to complex multi-provider configurations.

## Configuration Variables Reference

### Default LLM Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEFAULT_LLM_PROVIDER` | string | `openai` | LLM provider (openai, anthropic, ollama, azure, generic) |
| `DEFAULT_LLM_MODEL` | string | `gpt-5-mini` | Model identifier for the default LLM |
| `DEFAULT_LLM_BASE_URL` | string | `null` | Custom endpoint URL (optional) |
| `DEFAULT_LLM_API_KEY` | string | **required** | API key for the default LLM service |
| `DEFAULT_LLM_PROMPT` | string | `prompts/medical_triage.txt` | Path to prompt file for default analysis |

### Dual-LLM Feature

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DUAL_LLM_ENABLED` | boolean | `false` | Enable dual-LLM processing |
| `SECONDARY_LLM_PROVIDER` | string | `null` | Provider for secondary analysis |
| `SECONDARY_LLM_MODEL` | string | `null` | Model identifier for secondary LLM |
| `SECONDARY_LLM_BASE_URL` | string | `null` | Custom endpoint for secondary LLM |
| `SECONDARY_LLM_API_KEY` | string | `null` | API key for secondary LLM service |
| `SECONDARY_LLM_PROMPT` | string | `null` | Path to prompt file for secondary analysis |

### Common LLM Parameters

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LLM_TEMPERATURE` | float | `null` | Response creativity (0.0-2.0, optional) |
| `LLM_MAX_TOKENS` | integer | `null` | Maximum response length (optional) |

## Configuration Examples

### Example 1: Single LLM (OpenAI) - Current Setup

```bash
# .env
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_USER=@pdfbot:example.org
MATRIX_PASSWORD=super_secret_password
MATRIX_ROOM_ID=!yourroomid:example.org

# Default LLM (OpenAI GPT)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_api_key_here
DEFAULT_LLM_PROMPT=prompts/medical_triage.txt

# Dual LLM disabled
DUAL_LLM_ENABLED=false
```

### Example 2: Single LLM (Local Ollama)

```bash
# Default LLM (Local Ollama)
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_MODEL=llama3.1:8b
DEFAULT_LLM_BASE_URL=http://localhost:11434/v1
DEFAULT_LLM_API_KEY=not_required
DEFAULT_LLM_PROMPT=prompts/medical_triage.txt

# Dual LLM disabled
DUAL_LLM_ENABLED=false
```

### Example 3: Dual LLM (OpenAI + Anthropic)

```bash
# Default LLM (OpenAI)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_key_here
DEFAULT_LLM_PROMPT=prompts/medical_triage_primary.txt

# Enable dual processing
DUAL_LLM_ENABLED=true

# Secondary LLM (Anthropic Claude)
SECONDARY_LLM_PROVIDER=anthropic
SECONDARY_LLM_MODEL=claude-3-5-sonnet-20241022
SECONDARY_LLM_API_KEY=sk-your_anthropic_key_here
SECONDARY_LLM_PROMPT=prompts/medical_triage_secondary.txt

# Common parameters
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
```

### Example 4: Dual LLM (Cloud + Local)

```bash
# Default LLM (OpenAI)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_key_here
DEFAULT_LLM_PROMPT=prompts/medical_triage_standard.txt

# Enable dual processing
DUAL_LLM_ENABLED=true

# Secondary LLM (Local Ollama)
SECONDARY_LLM_PROVIDER=generic
SECONDARY_LLM_MODEL=qwen2.5:7b
SECONDARY_LLM_BASE_URL=http://localhost:11434/v1
SECONDARY_LLM_API_KEY=not_required
SECONDARY_LLM_PROMPT=prompts/medical_triage_experimental.txt
```

### Example 5: Azure OpenAI Configuration

```bash
# Default LLM (Azure OpenAI)
DEFAULT_LLM_PROVIDER=azure
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_BASE_URL=https://your-resource.openai.azure.com/
DEFAULT_LLM_API_KEY=your_azure_api_key
DEFAULT_LLM_PROMPT=prompts/medical_triage.txt

# Dual LLM disabled
DUAL_LLM_ENABLED=false
```

## Provider-Specific Configuration

### OpenAI

```bash
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini  # or gpt-4, gpt-3.5-turbo, etc.
DEFAULT_LLM_API_KEY=sk-...
# DEFAULT_LLM_BASE_URL not needed (uses default OpenAI endpoint)
```

### Anthropic Claude

```bash
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-3-5-sonnet-20241022  # or claude-3-opus, claude-3-haiku
DEFAULT_LLM_API_KEY=sk-ant-...
# DEFAULT_LLM_BASE_URL not needed (uses default Anthropic endpoint)
```

### Ollama (Local)

```bash
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_MODEL=llama3.1:8b  # or any locally available model
DEFAULT_LLM_BASE_URL=http://localhost:11434/v1
DEFAULT_LLM_API_KEY=not_required  # Ollama doesn't require API keys
```

### LM Studio (Local)

```bash
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_MODEL=local-model  # Model name as shown in LM Studio
DEFAULT_LLM_BASE_URL=http://localhost:1234/v1
DEFAULT_LLM_API_KEY=not_required  # LM Studio doesn't require API keys
```

### Azure OpenAI

```bash
DEFAULT_LLM_PROVIDER=azure
DEFAULT_LLM_MODEL=your-deployment-name  # Your Azure deployment name
DEFAULT_LLM_BASE_URL=https://your-resource.openai.azure.com/
DEFAULT_LLM_API_KEY=your_azure_api_key
```

### Custom OpenAI-Compatible API

```bash
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_MODEL=your-model-name
DEFAULT_LLM_BASE_URL=https://your-custom-api.com/v1
DEFAULT_LLM_API_KEY=your_custom_api_key
```

## Prompt File Configuration

### Creating Prompt Files

Create specialized prompt files for different analysis approaches:

**Primary Analysis** (`prompts/medical_triage_primary.txt`):
```text
Você é um especialista em triagem médica vascular brasileira.

Analise este relatório médico focando em:
1. Indicações urgentes para cirurgia vascular
2. Fatores de risco cardiovascular
3. Prognóstico e recomendações

Forneça uma análise estruturada e concisa em português.
```

**Secondary Analysis** (`prompts/medical_triage_secondary.txt`):
```text
Você é um segundo opinião médica especializada em medicina interna.

Analise este relatório médico focando em:
1. Diagnósticos diferenciais não considerados
2. Exames complementares necessários
3. Contraindicações para procedimentos

Forneça uma segunda opinião crítica e detalhada em português.
```

### Prompt File Best Practices

1. **Use UTF-8 encoding** for special characters
2. **Keep prompts focused** on specific analysis goals
3. **Include language preferences** (português, english, etc.)
4. **Specify output format** if needed (structured, bullet points, etc.)
5. **Add context about medical specialization** for domain-specific analysis

## Migration from Current Setup

### Step 1: Backup Current Configuration

```bash
cp .env .env.backup
```

### Step 2: Update Configuration Variables

Replace existing variables:

```bash
# OLD (still supported)
OPENAI_API_KEY=your_key
LLM_MODEL=gpt-5-mini
PROMPT_FILE=prompts/medical_triage.txt

# NEW (recommended)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_API_KEY=your_key
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_PROMPT=prompts/medical_triage.txt
DUAL_LLM_ENABLED=false
```

### Step 3: Test Single-LLM Operation

Verify the bot works with new configuration before enabling dual mode.

### Step 4: Enable Dual Mode (Optional)

Add secondary LLM configuration and set `DUAL_LLM_ENABLED=true`.

## Troubleshooting

### Common Configuration Errors

#### Error: "DEFAULT_LLM_API_KEY is required"
**Solution**: Ensure you've set the API key for your chosen provider.

#### Error: "SECONDARY_LLM_API_KEY required when DUAL_LLM_ENABLED=true"
**Solution**: When dual mode is enabled, you must configure the secondary LLM.

#### Error: "Prompt file not found"
**Solution**: Ensure prompt file paths are correct and files exist.

#### Error: "Unsupported LLM provider"
**Solution**: Use supported providers: `openai`, `anthropic`, `azure`, `ollama`, `generic`.

### Performance Considerations

#### Single LLM Mode
- **Processing time**: ~30-60 seconds per PDF
- **Cost**: Single API call per PDF
- **Memory**: Low usage

#### Dual LLM Mode
- **Processing time**: ~45-90 seconds per PDF (parallel processing)
- **Cost**: 2x API calls per PDF
- **Memory**: Moderate increase

#### Recommendations
- **Start with single LLM** to establish baseline performance
- **Enable dual mode** for evaluation periods or critical documents
- **Monitor API usage costs** when dual mode is enabled
- **Use local models** (Ollama) for cost-effective secondary analysis

### Testing Your Configuration

#### Test 1: Configuration Validation
Start the bot and check for configuration errors in the logs.

#### Test 2: Single PDF Processing
Upload a test PDF and verify:
- Processing message appears
- Analysis is posted within reasonable time
- No error messages in logs

#### Test 3: Dual Mode (if enabled)
Upload a test PDF and verify:
- Two separate analysis messages are posted
- Both analyses reply to the original PDF message
- Processing time is reasonable (~2x single mode)

## Advanced Configuration

### Custom Response Formatting

You can customize how dual responses are formatted by modifying the message prefixes in the bot code:

```python
# Primary analysis
"body": f"🤖 **Análise Primária**\n\n{results['default']}"

# Secondary analysis  
"body": f"🔍 **Análise Secundária**\n\n{results['secondary']}"
```

### Model-Specific Parameters

Some models support additional parameters:

```bash
# For creative analysis
LLM_TEMPERATURE=1.0

# For conservative analysis
LLM_TEMPERATURE=0.3

# For longer responses
LLM_MAX_TOKENS=4000

# For shorter responses
LLM_MAX_TOKENS=1000
```

### Environment-Specific Configurations

#### Development Environment

```bash
# Use cheaper/faster models for development
DEFAULT_LLM_MODEL=gpt-3.5-turbo
SECONDARY_LLM_PROVIDER=generic
SECONDARY_LLM_BASE_URL=http://localhost:11434/v1
```

#### Production Environment

```bash
# Use high-quality models for production
DEFAULT_LLM_MODEL=gpt-5-mini
SECONDARY_LLM_MODEL=claude-3-5-sonnet-20241022
```

#### Cost-Optimized Environment

```bash
# Use local models to minimize costs
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_BASE_URL=http://localhost:11434/v1
SECONDARY_LLM_PROVIDER=generic
SECONDARY_LLM_BASE_URL=http://localhost:11434/v1
```