# **Development Guide: Lightweight Qwen Agents on Hailo with Context Priming**

## **1\. Executive Summary**

This guide outlines the architecture for building a Python-based agent using the **Qwen2.5-Coder-1.5B-Instruct** model on Hailo hardware.

**The Core Challenge:** The hardware imposes a strict **2048 token context window**. Standard agentic workflows—which typically involve verbose system prompts, heavy JSON schemas, and long histories—will rapidly exhaust this limit. Furthermore, while the "prefill" (processing input) is fast on Hailo, "decoding" (generating output) is slower and computationally expensive.

**The Solution:** We utilize a **"State Priming" strategy**. We leverage the model's save\_state / load\_state capabilities to pre-compute the KV cache for the static portion of the prompt (System Instructions \+ Tool Definitions \+ Few-Shot Examples). This effectively "compiles" your agent's persona and capabilities into a binary state file. At runtime, the agent wakes up "primed" with this knowledge, incurring zero latency for the system prompt and maximizing the remaining context for the user's query.

## **2\. Architectural Strategy: The "Build vs. Run" Workflow**

We split the agent lifecycle into two distinct phases to optimize for the 2K limit and generation speed.

### **2.1 Build Time (State Generation)**

This is an offline process run once (or whenever tools change). Its goal is to create a serialized agent\_prime.state file.

1. **Construct Static Prompt:** Assemble the System Prompt, Tool Definitions, and Few-Shot Examples.  
   * **Crucial:** This must use the exact control tokens expected by the model (e.g., ChatML format \<|im\_start|\>system...). If the structure is wrong, the primed state will be corrupted.  
2. **Prefill Inference:** Feed this static prompt into the Hailo engine *without* generating a response.  
3. **Serialize:** Call save\_state("agent\_prime.state") to dump the KV cache to disk.

### **2.2 Run Time (The Inference Loop)**

This is the live application loop.

1. **Load State:** Initialize the model by calling load\_state("agent\_prime.state"). This restores the context instantly.  
2. **User Input:** Append the user's query using the proper user prompt structure (\<|im\_start|\>user...).  
3. **Generate:** Run inference. Since the model is already primed, it moves immediately to generation.  
4. **Tool Execution:** Parse the output, execute the Python tool, and observe the result.  
5. **Reset (Optional):** Due to the 2K limit, extensive history is impossible. A recommended pattern is to **reload the prime state** after every completed task to clear the context window, rather than trying to maintain a long conversation history.

## **3\. Prompt Engineering for 2K Context & Weak Models**

With only \~2048 tokens, every character counts. We must prioritize "reading" (which is fast and cached) over "writing" (which is slow).

### **3.1 Tool Definition Strategy (Token vs. Accuracy Trade-off)**

You must choose a format for defining tools in the system prompt. This is a trade-off between the model's training data bias and your strict token budget.

**Option A: Minified JSON Schema (Recommended Starting Point)**

* *Why:* Qwen2.5 was fine-tuned heavily on OpenAI-style JSON schemas. It is the most reliable format for correctness.  
* *Optimization:* Strip all whitespace, newlines, and non-essential fields to save tokens.  
* *Example:* {"name":"get\_temp","parameters":{"type":"object","properties":{"city":{"type":"string"}}}}

**Option B: TypeScript Signatures (High Efficiency / High Risk)**

* *Why:* Qwen2.5-Coder is a *coding* model. It understands syntax. TypeScript signatures are 30-50% more compact than JSON schemas.  
* *Risk:* The model might not be fine-tuned to *call* tools defined this way as robustly as JSON.  
* *Mitigation:* If you use this, you **must** include a few-shot example in the prime state showing the model how to translate a TypeScript definition into a tool call.  
* *Example:* get\_temp(city: str) \-\> str // gets temperature

### **3.2 Few-Shot Priming (The "Golden Rule")**

"Weak" models (1.5B) struggle with complex abstract instructions. They rely on pattern matching.  
In your Build Phase, include 2-3 examples of the interaction flow directly in the prompt before saving the state.  
Structure for Priming:  
\<|im\_start|\>system  
You are an agent...  
Tools:...  
\<|im\_end|\>  
\<|im\_start|\>user  
Turn on the light.  
\<|im\_end|\>  
\<|im\_start|\>assistant  
\<tool\_call\>set\_light(state="on")\</tool\_call\>  
\<|im\_end|\>  
By saving this exact sequence in the state, the model is statistically "forced" to follow the pattern \<tool\_call\>... when the next user input arrives.

### **3.3 Output Minimization**

Since token-by-token generation is the bottleneck:

* **Suppress "Chain of Thought":** Do not ask the model to "think step by step" for simple tools. It wastes generation time and context space.  
* **Concise Instructions:** Add "Reply with only the tool call" to the system prompt.  
* **Truncate Observations:** When feeding tool results back to the model, truncate them (e.g., to 100 chars). Do not feed back massive logs, or you will hit the 2K wall immediately.

## **4\. Cursor Development Guidelines**

To implement this, you need to set up Cursor to generate code that respects these architectural constraints.

### **4.1 .cursorrules (Project Context)**

Place this file in your root directory. It tells Cursor how to write code for your specific constraints.

# **Cursor Rules for Hailo Qwen Agent (2K Context Limit)**

## **1\. Architecture: State Priming**

* **Pattern:** The application uses a "Load/Save State" architecture.  
* **Constraint:** The model has a hard limit of **2048 tokens**.  
* **Code Style:** Python 3.10+, modular, type-hinted.

## **2\. Prompting Strategy (Crucial)**

* **Structure:** All prompts generated in code MUST strictly adhere to the ChatML format: \<|im\_start|\>system...\<|im\_end|\>.  
* **Tool Format:**  
  * Create a configuration toggle: TOOL\_FORMAT \= "json" | "typescript".  
  * Default to **Minified JSON** for reliability.  
  * Implement **TypeScript signatures** as an option for extreme token saving.  
* **Few-Shot:** The create\_prime\_state script MUST include 2-3 static examples of user/assistant interaction.  
* **Output:** Force the model to use XML tags for tools: \<tool\_call\>func(arg=val)\</tool\_call\>. This is easier to regex-parse from a weak model's output than strict JSON.

## **3\. Python Implementation Guidelines**

* **State Management:**  
  * Create a StateManger class.  
  * prime\_model(): Constructs full prompt \-\> runs prefill \-\> calls save\_state.  
  * load\_session(): Calls load\_state before processing user input.  
* **Token Budgeting:**  
  * Implement a strict token counter.  
  * **Rule:** len(system) \+ len(tools) \+ len(examples) \< 1500\. Leave at least 500 tokens for the active turn.  
* **Tool Execution:**  
  * Return values from tools must be truncated\! If a tool returns 500 lines of log, the next prompt will overflow. Truncate tool outputs to \~200 tokens.

## **4\. "Weak Model" Defensiveness**

* **Validation:** The 1.5B model *will* hallucinate function names.  
* **Repair:** Implement a retry loop. If eval(tool\_call) fails, feed a short error back: "Invalid tool. Try again."  
* **Regex Parsing:** Do not rely on json.loads for the tool call itself. Use Regex to extract the function name and arguments from the \<tool\_call\> tags.

### **4.2 Development Workflow with Cursor**

Step 1: Generate the Tool Registry  
Prompt: "Create a tools.py with a registry decorator. Implement a function get\_tool\_definitions(format) that returns either a minified JSON schema string or a TypeScript signature string. Ensure the docstrings are parsed correctly."  
Step 2: Generate the State Builder  
Prompt: "Create a build\_state.py script. It should import the tool definitions, construct a ChatML formatted system prompt with 3 hardcoded few-shot examples, and simulate the Hailo save\_state API to create a 'prime' file."  
Step 3: Generate the Runtime Loop  
Prompt: "Write the main agent loop. It should load the primed state. When receiving user input, verify we are under the 2K limit. Generate response. Parse XML tool calls. Crucial: If the context approaches 1900 tokens, force a reset to the initial primed state."

## **5\. Summary of Best Practices**

| Feature | Best Practice for Hailo Qwen 1.5B | Why? |
| :---- | :---- | :---- |
| **Context** | **State Priming** (Save/Load) | Avoids re-processing 1500+ system tokens every turn. |
| **Tool Defs** | **Minified JSON** (Start here) | Matches training data. Use TypeScript only if 2K limit is critical. |
| **Structure** | **Strict ChatML** | \`\< |
| **Logic** | **Few-Shot Examples** | Weak models follow examples better than abstract instructions. |
| **Output** | **Minimal / No-CoT** | CoT fills the 2K context too fast. Use only for complex reasoning. |
| **Safety** | **Output Truncation** | Never feed full tool outputs back to the model. It kills context. |

