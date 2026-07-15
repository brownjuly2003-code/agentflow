{{/*
Common container env for API and worker Deployments.
Caller: include "agentflow.containerEnv" (dict "root" . "secretName" $secretName "processRole" "api")
processRole may be "" (omit AGENTFLOW_PROCESS_ROLE — app default 'all').
*/}}
{{- define "agentflow.containerEnv" -}}
{{- $root := .root -}}
{{- $secretName := .secretName -}}
{{- $processRole := .processRole | default "" -}}
- name: SERVING_BACKEND
  value: {{ $root.Values.serving.backend | quote }}
{{- if eq $root.Values.serving.backend "clickhouse" }}
- name: CLICKHOUSE_HOST
  value: {{ required "serving.clickhouse.host is required when serving.backend=clickhouse" $root.Values.serving.clickhouse.host | quote }}
- name: CLICKHOUSE_PORT
  value: {{ $root.Values.serving.clickhouse.port | quote }}
- name: CLICKHOUSE_DATABASE
  value: {{ $root.Values.serving.clickhouse.database | quote }}
- name: CLICKHOUSE_USER
  value: {{ $root.Values.serving.clickhouse.user | quote }}
{{- if $root.Values.serving.clickhouse.existingSecret }}
- name: CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $root.Values.serving.clickhouse.existingSecret | quote }}
      key: {{ $root.Values.serving.clickhouse.passwordKey | quote }}
{{- end }}
- name: CLICKHOUSE_SECURE
  value: {{ $root.Values.serving.clickhouse.secure | quote }}
{{- if $root.Values.serving.clickhouse.tls.caSecret }}
- name: CLICKHOUSE_CA_CERT
  value: /etc/agentflow/tls/clickhouse/{{ $root.Values.serving.clickhouse.tls.caKey }}
{{- end }}
{{- end }}
- name: AGENTFLOW_CONTROLPLANE_STORE
  value: {{ $root.Values.controlPlane.store | quote }}
{{- if eq $root.Values.controlPlane.store "postgres" }}
- name: AGENTFLOW_CONTROLPLANE_PG_DSN
  valueFrom:
    secretKeyRef:
      name: {{ required "controlPlane.postgres.existingSecret is required when controlPlane.store=postgres (it must hold the PostgreSQL DSN; the chart ships no PG service)" $root.Values.controlPlane.postgres.existingSecret | quote }}
      key: {{ $root.Values.controlPlane.postgres.dsnKey | quote }}
{{- end }}
{{- if $processRole }}
- name: AGENTFLOW_PROCESS_ROLE
  value: {{ $processRole | quote }}
{{- end }}
- name: DUCKDB_PATH
  value: {{ $root.Values.config.duckdbPath | quote }}
- name: AGENTFLOW_USAGE_DB_PATH
  value: {{ $root.Values.config.usageDbPath | quote }}
- name: AGENTFLOW_API_KEYS_FILE
  value: {{ $root.Values.config.apiKeysPath | quote }}
- name: AGENTFLOW_TENANTS_FILE
  value: {{ $root.Values.config.tenantsPath | quote }}
- name: AGENTFLOW_SLO_FILE
  value: {{ $root.Values.config.sloPath | quote }}
- name: AGENTFLOW_SECURITY_CONFIG_FILE
  value: {{ $root.Values.config.securityPath | quote }}
- name: AGENTFLOW_API_VERSIONS_FILE
  value: {{ $root.Values.config.apiVersionsPath | quote }}
- name: AGENTFLOW_CONTRACTS_DIR
  value: {{ $root.Values.config.contractsDir | quote }}
- name: AGENTFLOW_RATE_LIMIT_RPM
  value: {{ $root.Values.config.rateLimitRpm | quote }}
- name: CACHE_TTL_SECONDS
  value: {{ $root.Values.config.cacheTtlSeconds | quote }}
{{- if $root.Values.config.profile }}
- name: AGENTFLOW_PROFILE
  value: {{ $root.Values.config.profile | quote }}
{{- end }}
- name: AGENTFLOW_CORS_ORIGINS
  value: {{ $root.Values.config.corsOrigins | quote }}
- name: AGENTFLOW_ADMIN_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: admin-key
{{- if $root.Values.config.redisUrl }}
- name: REDIS_URL
  value: {{ $root.Values.config.redisUrl | quote }}
{{- end }}
{{- if $root.Values.config.otlpEndpoint }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ $root.Values.config.otlpEndpoint | quote }}
- name: OTEL_SERVICE_NAME
  value: {{ $root.Values.config.otlpServiceName | quote }}
{{- end }}
{{- with $root.Values.extraEnv }}
{{/* Leading newline required: {{- toYaml }} would glue onto the previous value. */}}
{{ toYaml . }}
{{- end }}
{{- end -}}
