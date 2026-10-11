# Azure OpenAI Basic Example

This example shows how to use CortexOps tracing with Azure OpenAI models using LangChain's `AzureChatOpenAI` wrapper.

## Setup

Make sure you have installed the required dependencies:

```bash
pip install cortexops langchain-openai python-dotenv
```

Set your environment variables in your terminal or in a `.env` file:

```bash
export CORTEXOPS_API_KEY="cxo-your-api-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource-name.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-azure-api-key"
export OPENAI_API_VERSION="2024-10-21"
export AZURE_OPENAI_DEPLOYMENT_NAME="your-deployment-name"
```

You can obtain your CortexOps API key from `cortexops login` or the dashboard. When `CORTEXOPS_API_KEY` is set, traces appear under the `azure-openai-basic` project at https://getcortexops.com.

> **Note**: The generic wrapper records the reply as text, without model name or token counts.

## Running the Example

Run the python script to trigger a traced call:

```bash
python main.py
```
