package main

import (
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
)

// Main é o ponto de entrada principal para a Action do Apache OpenWhisk em Go.
// Recebe um payload JSON como map[string]interface{} e retorna o resultado e um erro opcional.
func Main(params map[string]interface{}) (map[string]interface{}, error) {
	// 1. Validação de parâmetros de entrada
	payloadRaw, ok := params["payload"]
	if !ok {
		return nil, errors.New("parametro 'payload' e obrigatorio")
	}

	payload, ok := payloadRaw.(string)
	if !ok {
		return nil, errors.New("parametro 'payload' deve ser uma string")
	}

	payload = strings.TrimSpace(payload)
	if payload == "" {
		return nil, errors.New("parametro 'payload' nao pode ser vazio")
	}

	// Recuperar ou definir o nome do arquivo opcional
	fileName := "document.txt"
	if fn, ok := params["file_name"].(string); ok && strings.TrimSpace(fn) != "" {
		fileName = strings.TrimSpace(fn)
	}

	// 2. Cálculo dos hashes criptográficos para integridade de dados e auditoria
	md5Hasher := md5.New()
	md5Hasher.Write([]byte(payload))
	md5Hash := hex.EncodeToString(md5Hasher.Sum(nil))

	shaHasher := sha256.New()
	shaHasher.Write([]byte(payload))
	sha256Hash := hex.EncodeToString(shaHasher.Sum(nil))

	// 3. Estruturação dos metadados extraídos
	meta := map[string]interface{}{
		"original_length": len(payload),
		"word_count":      len(strings.Fields(payload)),
		"is_binary":       strings.Contains(payload, "\\x"),
		"md5_hash":        md5Hash,
		"sha256_hash":     sha256Hash,
	}

	// 4. Retorno do payload estruturado com suporte a pipeline
	response := map[string]interface{}{
		"status":      "success",
		"message":     "Payload validado e hashes criptograficos calculados com sucesso.",
		"file_name":   fileName,
		"raw_payload": payload,
		"metadata":    meta,
	}

	return response, nil
}

// Para testes locais fora do OpenWhisk
func main() {
	testParams := map[string]interface{}{
		"payload":   "   Mensagem corporativa secreta para processar hashes no OpenWhisk.   ",
		"file_name": "dados_vendas.csv",
	}
	result, err := Main(testParams)
	if err != nil {
		fmt.Printf("Erro de execução: %v\n", err)
		return
	}
	fmt.Printf("Sucesso: %+v\n", result)
}
