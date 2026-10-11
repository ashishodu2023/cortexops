{{/* Chart name. */}}
{{- define "cortexops.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Fully qualified app name, truncated to 63 chars for DNS names. */}}
{{- define "cortexops.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "cortexops.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Common labels. */}}
{{- define "cortexops.labels" -}}
helm.sh/chart: {{ include "cortexops.chart" . }}
app.kubernetes.io/name: {{ include "cortexops.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: cortexops
{{- end }}

{{/* Selector labels for a component. Usage: include "cortexops.selectorLabels" (dict "ctx" . "component" "api") */}}
{{- define "cortexops.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cortexops.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* Labels for a component's resources. */}}
{{- define "cortexops.componentLabels" -}}
{{ include "cortexops.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "cortexops.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cortexops.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "cortexops.secretName" -}}
{{- default (include "cortexops.fullname" .) .Values.secrets.existingSecret }}
{{- end }}

{{- define "cortexops.configMapName" -}}
{{- include "cortexops.fullname" . }}
{{- end }}

{{- define "cortexops.apiImage" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{- define "cortexops.dashboardImage" -}}
{{- printf "%s:%s" .Values.dashboard.image.repository (default .Chart.AppVersion .Values.dashboard.image.tag) }}
{{- end }}

{{/* "https" when the host is listed under ingress.tls, otherwise "http". Usage: (dict "ctx" . "host" "a.example.com") */}}
{{- define "cortexops.hostScheme" -}}
{{- $scheme := "http" }}
{{- range .ctx.Values.ingress.tls }}
{{- if has $.host (default list .hosts) }}
{{- $scheme = "https" }}
{{- end }}
{{- end }}
{{- $scheme }}
{{- end }}

{{/* API URL as seen from the browser. */}}
{{- define "cortexops.apiUrl" -}}
{{- if .Values.dashboard.apiUrl }}
{{- .Values.dashboard.apiUrl | trimSuffix "/" }}
{{- else if .Values.ingress.enabled }}
{{- $host := .Values.ingress.api.host }}
{{- printf "%s://%s" (include "cortexops.hostScheme" (dict "ctx" . "host" $host)) $host }}
{{- else }}
{{- print "http://localhost:8000" }}
{{- end }}
{{- end }}

{{/* Dashboard URL as seen from the browser. */}}
{{- define "cortexops.dashboardUrl" -}}
{{- if .Values.ingress.enabled }}
{{- $host := .Values.ingress.dashboard.host }}
{{- printf "%s://%s" (include "cortexops.hostScheme" (dict "ctx" . "host" $host)) $host }}
{{- else }}
{{- print "http://localhost:3000" }}
{{- end }}
{{- end }}

{{- define "cortexops.postgresql.fullname" -}}
{{- printf "%s-postgresql" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "cortexops.redis.fullname" -}}
{{- printf "%s-redis" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Env vars wiring the bundled PostgreSQL/Redis subcharts; they take precedence over the Secret (envFrom). */}}
{{- define "cortexops.dependencyEnv" -}}
{{- if .Values.postgresql.enabled }}
- name: CORTEXOPS_POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ default (include "cortexops.postgresql.fullname" .) .Values.postgresql.auth.existingSecret }}
      key: {{ dig "auth" "secretKeys" "userPasswordKey" "password" .Values.postgresql | default "password" }}
- name: DATABASE_URL
  value: {{ printf "postgresql+asyncpg://%s:$(CORTEXOPS_POSTGRES_PASSWORD)@%s:5432/%s" .Values.postgresql.auth.username (include "cortexops.postgresql.fullname" .) .Values.postgresql.auth.database | quote }}
{{- end }}
{{- if .Values.redis.enabled }}
{{- $redisHost := printf "%s-master:6379" (include "cortexops.redis.fullname" .) }}
{{- $auth := "" }}
{{- if .Values.redis.auth.enabled }}
{{- $auth = ":$(CORTEXOPS_REDIS_PASSWORD)@" }}
- name: CORTEXOPS_REDIS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ default (include "cortexops.redis.fullname" .) .Values.redis.auth.existingSecret }}
      key: {{ dig "auth" "existingSecretPasswordKey" "redis-password" .Values.redis | default "redis-password" }}
{{- end }}
- name: REDIS_URL
  value: {{ printf "redis://%s%s/0" $auth $redisHost | quote }}
- name: CELERY_BROKER_URL
  value: {{ printf "redis://%s%s/0" $auth $redisHost | quote }}
- name: CELERY_RESULT_BACKEND
  value: {{ printf "redis://%s%s/1" $auth $redisHost | quote }}
{{- end }}
{{- end }}

{{/* envFrom shared by the API, worker and migration job. */}}
{{- define "cortexops.envFrom" -}}
- configMapRef:
    name: {{ include "cortexops.configMapName" . }}
- secretRef:
    name: {{ include "cortexops.secretName" . }}
{{- end }}

{{/* Pod annotations that roll pods when config changes. */}}
{{- define "cortexops.configChecksums" -}}
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- if not .Values.secrets.existingSecret }}
checksum/secret-inputs: {{ toJson (list .Values.secrets .Values.externalDatabase .Values.externalRedis) | sha256sum }}
{{- end }}
{{- end }}

{{/* True when a database is configured through one of the supported mechanisms. */}}
{{- define "cortexops.databaseConfigured" -}}
{{- if or .Values.postgresql.enabled .Values.externalDatabase.url .Values.secrets.existingSecret }}true{{ end }}
{{- end }}
