'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchCredits } from '@/lib/client-api';

export function useCredits() {
  return useQuery({
    queryKey: ['credits'],
    queryFn: () => fetchCredits(),
    staleTime: 20_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}
