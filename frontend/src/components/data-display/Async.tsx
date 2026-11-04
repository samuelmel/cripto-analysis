import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ErrorState, LoadingBlock } from "../ui/primitives";

export function Async<T>({
  query,
  children,
  loadingLabel,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}): ReactNode {
  if (query.isPending) return loadingLabel ? <LoadingBlock label={loadingLabel} /> : <LoadingBlock />;
  if (query.isError) {
    return <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />;
  }
  return children(query.data);
}
