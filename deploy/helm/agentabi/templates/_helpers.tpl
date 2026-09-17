{{- define "agentabi.labels" -}}
app.kubernetes.io/part-of: agentabi
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agentabi.image" -}}
{{- printf "%s/%s:%s" .registry .repository .tag -}}
{{- end -}}
