{{/*
Kafka SASL/TLS environment shared by the Flink job and both materializers.
The calling template owns the optional kafka-ca volume mount.
*/}}
{{- define "agentflow.kafkaAuthEnv" -}}
{{- $root := . -}}
{{- if and (eq $root.Values.config.profile "production") (not $root.Values.kafkaAuth.enabled) }}
{{- fail "production Kafka workloads require kafkaAuth.enabled=true (SASL/TLS is fail-closed)" }}
{{- end }}
- name: AGENTFLOW_KAFKA_AUTH_ENABLED
  value: {{ $root.Values.kafkaAuth.enabled | quote }}
{{- if $root.Values.kafkaAuth.enabled }}
- name: AGENTFLOW_KAFKA_SECURITY_PROTOCOL
  value: {{ $root.Values.kafkaAuth.securityProtocol | quote }}
- name: AGENTFLOW_KAFKA_SASL_MECHANISM
  value: {{ $root.Values.kafkaAuth.saslMechanism | quote }}
- name: AGENTFLOW_KAFKA_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ required "kafkaAuth.existingSecret is required when kafkaAuth.enabled=true" $root.Values.kafkaAuth.existingSecret | quote }}
      key: {{ $root.Values.kafkaAuth.usernameKey | quote }}
- name: AGENTFLOW_KAFKA_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $root.Values.kafkaAuth.existingSecret | quote }}
      key: {{ $root.Values.kafkaAuth.passwordKey | quote }}
{{- if $root.Values.kafkaAuth.caSecret }}
- name: AGENTFLOW_KAFKA_CA_PATH
  value: /etc/agentflow/kafka/{{ $root.Values.kafkaAuth.caKey }}
{{- end }}
{{- end }}
{{- end -}}
