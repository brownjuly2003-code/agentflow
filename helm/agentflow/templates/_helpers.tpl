{{- define "agentflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agentflow.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "agentflow.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "agentflow.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agentflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agentflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "agentflow.labels" -}}
helm.sh/chart: {{ include "agentflow.chart" . }}
{{ include "agentflow.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agentflow.imageReference" -}}
{{- if .digest -}}
{{- printf "%s@%s" .repository .digest -}}
{{- else -}}
{{- printf "%s:%s" .repository .tag -}}
{{- end -}}
{{- end -}}

{{- define "agentflow.apiServiceAccountName" -}}
{{- coalesce .Values.serviceAccount.name .Values.serviceAccount.apiName (printf "%s-api" (include "agentflow.fullname" . | trunc 59 | trimSuffix "-")) -}}
{{- end -}}

{{- define "agentflow.workerServiceAccountName" -}}
{{- coalesce .Values.serviceAccount.name .Values.serviceAccount.workerName (printf "%s-worker" (include "agentflow.fullname" . | trunc 56 | trimSuffix "-")) -}}
{{- end -}}

{{- define "agentflow.provisionServiceAccountName" -}}
{{- coalesce .Values.serviceAccount.name .Values.serviceAccount.provisionName (printf "%s-provision" (include "agentflow.fullname" . | trunc 53 | trimSuffix "-")) -}}
{{- end -}}

{{- define "agentflow.flinkServiceAccountName" -}}
{{- coalesce .Values.serviceAccount.name .Values.flinkJob.serviceAccount (printf "%s-flink" (include "agentflow.fullname" . | trunc 57 | trimSuffix "-")) -}}
{{- end -}}

{{- define "agentflow.serviceAccountName" -}}
{{- include "agentflow.apiServiceAccountName" . -}}
{{- end -}}

{{/*
One egress rule: a port, and the destinations reachable on it.
Caller: include "agentflow.egressRule" (dict "to" $destinations "port" $port)

A Kubernetes egress rule with `ports:` and no `to:` allows those ports to
EVERY address -- in the cluster and on the internet (audit FB-09). So an empty
destination list is not a narrower policy, it is the widest one, and the
production contract refuses it for every rule this chart renders.
*/}}
{{- define "agentflow.egressRule" -}}
{{- if .to }}
- to:
{{ toYaml .to | indent 4 }}
  ports:
    - protocol: TCP
      port: {{ .port }}
{{- else }}
- ports:
    - protocol: TCP
      port: {{ .port }}
{{- end }}
{{- end -}}
