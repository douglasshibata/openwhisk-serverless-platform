import json
import urllib.request
import time

def main(args):
    """
    Função principal para a Action do Apache OpenWhisk em Python.
    Pode rodar tanto em isolamento quanto após a Go Action em um pipeline (Sequence).
    """
    # 1. Recuperar parâmetros da execução (ou repassados pela Go Action anterior)
    raw_payload = args.get("raw_payload", args.get("payload"))
    file_name = args.get("file_name", "unknown_file.txt")
    metadata = args.get("metadata", {})
    status = args.get("status", "pending")

    if not raw_payload:
        return {
            "status": "error",
            "message": "Nenhum payload ou raw_payload fornecido para enriquecimento."
        }

    # 2. Transformações avançadas de dados
    # Normalizar para caixa alta e substituir espaços duplicados
    transformed_payload = " ".join(raw_payload.strip().upper().split())

    # 3. Integração com API Externa (Simulação com HTTP mock de alta resiliência)
    # Em um cenário produtivo, você chamaria um microsserviço ou API Gateway externo.
    enrichment_endpoint = "https://jsonplaceholder.typicode.com/posts/1"
    enrichment_info = {
        "status": "offline_mode",
        "description": "API Gateway de enriquecimento simulado devido a restrições de sandbox."
    }

    try:
        # Fazer uma requisição HTTP real para demonstração prática
        req = urllib.request.Request(
            enrichment_endpoint,
            headers={'User-Agent': 'Mozilla/5.0 (OpenWhisk-Enterprise-Agent)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                api_data = json.loads(response.read().decode('utf-8'))
                enrichment_info = {
                    "status": "online_enriched",
                    "source": enrichment_endpoint,
                    "external_id": api_data.get("id"),
                    "external_title": api_data.get("title")
                }
    except Exception as e:
        # Fallback resiliente para garantir que o pipeline FaaS não quebre
        enrichment_info = {
            "status": "enriched_fallback",
            "error_detail": str(e),
            "source": enrichment_endpoint
        }

    # 4. Enriquecer o dicionário de metadados existente
    enriched_metadata = dict(metadata)
    enriched_metadata.update({
        "processed_by": "Python-Action-v3.0",
        "execution_timestamp": int(time.time()),
        "transformed_length": len(transformed_payload),
        "enrichment": enrichment_info
    })

    # 5. Construir resposta estruturada de saída para o próximo nó ou cliente final
    return {
        "status": "fully_processed",
        "message": "Pipeline de dados concluido. Payload processado em Go e enriquecido em Python.",
        "file_name": file_name,
        "original_payload": raw_payload,
        "transformed_payload": transformed_payload,
        "final_metadata": enriched_metadata
    }

# Para testes e verificações locais fora do runtime OpenWhisk
if __name__ == "__main__":
    sample_input = {
        "raw_payload": "   Texto de entrada inicial para fins de teste local do script python   ",
        "file_name": "relatorio_mensal.xlsx",
        "metadata": {
            "original_length": 68,
            "word_count": 11,
            "md5_hash": "f68c347ad68b9cf1",
            "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        }
    }
    result = main(sample_input)
    print(json.dumps(result, indent=4))
