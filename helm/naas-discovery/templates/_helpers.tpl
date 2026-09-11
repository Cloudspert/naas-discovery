{{- define "naas-discovery.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "naas-discovery.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "naas-discovery.labels" -}}
app.kubernetes.io/name: {{ include "naas-discovery.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "naas-discovery.selectorLabels" -}}
app.kubernetes.io/name: {{ include "naas-discovery.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "naas-discovery.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "naas-discovery.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
