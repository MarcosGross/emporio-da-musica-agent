# Example conversations

Recorded with the real agent by `scripts/record_conversations.py` from the scripts in
`scripts/conversations.yaml`. Agent replies are unedited.

| File | Scenario | What it demonstrates |
| --- | --- | --- |
| [01-catalogo.md](01-catalogo.md) | Catalog search with a price limit, then asking for the results left out | Instrument type sent as `category`; the agent reports the total (12) when only 10 are returned and fetches the remaining 2 with a second search. |
| [02-preco.md](02-preco.md) | Price of a specific product, then installment options | Product lookup by approximate name; price, PIX and installments quoted from the tool result (pricing.py), not calculated by the model. |
| [03-loja.md](03-loja.md) | Store information questions | Answers from the policy manual in the system prompt, without tools. |
| [04-devolucao.md](04-devolucao.md) | Return request, identifying the order step by step | No promise before seeing the order; asks for the order number and contact (LGPD), then states the 7-day rule next to the order's status and recorded dates, says the actual receipt date is not recorded and refers to human support to confirm. |
| [05-escopo.md](05-escopo.md) | Accessories, prompt injection and an off-topic request | Store scope (instruments only), refusal to reveal instructions, and a one-line refusal of off-topic requests, each time steering back to instruments. |
