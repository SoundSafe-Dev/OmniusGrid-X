import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { errorTriageApi } from '../api/errorTriage';
import {
  ErrorListParams,
  ErrorListResponse,
  ErrorSummary,
  ErrorEventDetail,
  ErrorRange,
  ErrorStatus,
} from '../types/errorTriage';

const ERROR_TRIAGE_KEY = 'errorTriage';
const REFRESH_MS = 30_000;

export function useErrorList(params: ErrorListParams) {
  return useQuery<ErrorListResponse, Error>({
    queryKey: [ERROR_TRIAGE_KEY, 'list', params],
    queryFn: () => errorTriageApi.list(params),
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useErrorSummary(range: ErrorRange) {
  return useQuery<ErrorSummary, Error>({
    queryKey: [ERROR_TRIAGE_KEY, 'summary', range],
    queryFn: () => errorTriageApi.summary(range),
    refetchInterval: REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useErrorDetail(fingerprint: string) {
  return useQuery<ErrorEventDetail, Error>({
    queryKey: [ERROR_TRIAGE_KEY, 'detail', fingerprint],
    queryFn: () => errorTriageApi.detail(fingerprint),
    enabled: Boolean(fingerprint),
    refetchInterval: REFRESH_MS,
  });
}

export function useUpdateErrorStatus() {
  const queryClient = useQueryClient();
  return useMutation<
    ErrorEventDetail,
    Error,
    { fingerprint: string; status: ErrorStatus }
  >({
    mutationFn: ({ fingerprint, status }) => errorTriageApi.updateStatus(fingerprint, status),
    onSuccess: (data) => {
      queryClient.setQueryData([ERROR_TRIAGE_KEY, 'detail', data.fingerprint], data);
      queryClient.invalidateQueries({ queryKey: [ERROR_TRIAGE_KEY] });
    },
  });
}
