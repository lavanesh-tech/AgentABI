import type { ReactNode } from "react";
import { ApiError } from "@/lib/api-client";
import { friendlyErrorMessage } from "@/lib/api-client";
import { EmptyState, ErrorState, LoadingBlock } from "./primitives";

/** Shared loading/error/empty handling (spec §30/§31) so every screen
 * gets consistent, non-blank states without re-deriving this logic. */
export function QueryState<T>({
  isLoading,
  isError,
  error,
  data,
  isEmpty,
  emptyMessage,
  emptyHint,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  isEmpty?: (data: T) => boolean;
  emptyMessage: string;
  emptyHint?: string;
  children: (data: T) => ReactNode;
}) {
  if (isLoading) return <LoadingBlock />;
  if (isError) {
    return (
      <ErrorState
        message={friendlyErrorMessage(error)}
        requestId={error instanceof ApiError ? error.requestId : undefined}
      />
    );
  }
  if (data === undefined || (isEmpty && isEmpty(data))) {
    return <EmptyState message={emptyMessage} hint={emptyHint} />;
  }
  return <>{children(data)}</>;
}
