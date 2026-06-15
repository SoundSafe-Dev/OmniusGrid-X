import { useQuery, useMutation, useQueryClient } from 'react-query';
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
  return useQuery<ErrorListResponse, Error>(
    [ERROR_TRIAGE_KEY, 'list', params],
    () => errorTriageApi.list(params),
    {
      refetchInterval: REFRESH_MS,
      keepPreviousData: true,
    }
  );
}

export function useErrorSummary(range: ErrorRange) {
  return useQuery<ErrorSummary, Error>(
    [ERROR_TRIAGE_KEY, 'summary', range],
    () => errorTriageApi.summary(range),
    {
      refetchInterval: REFRESH_MS,
      keepPreviousData: true,
    }
  );
}

export function useErrorDetail(fingerprint: string) {
  return useQuery<ErrorEventDetail, Error>(
    [ERROR_TRIAGE_KEY, 'detail', fingerprint],
    () => errorTriageApi.detail(fingerprint),
    {
      enabled: Boolean(fingerprint),
      refetchInterval: REFRESH_MS,
    }
  );
}

export function useUpdateErrorStatus() {
  const queryClient = useQueryClient();
  return useMutation<
    ErrorEventDetail,
    Error,
    { fingerprint: string; status: ErrorStatus }
  >(
    ({ fingerprint, status }) => errorTriageApi.updateStatus(fingerprint, status),
    {
      onSuccess: (data) => {
        queryClient.setQueryData([ERROR_TRIAGE_KEY, 'detail', data.fingerprint], data);
        queryClient.invalidateQueries([ERROR_TRIAGE_KEY]);
      },
    }
  );
}
