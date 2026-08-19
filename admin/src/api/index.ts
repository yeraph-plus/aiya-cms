import type { ApiClient } from './client';

let api: ApiClient | null = null;

export function configureApi(client: ApiClient): void {
    api = client;
}

export function getApi(): ApiClient {
    if (api === null) {
        throw new Error('api client not configured; call configureApi from the composition root');
    }
    return api;
}

export { apiPath, createApiClient } from './client';
export type { ApiClient, ApiClientOptions, ApiPath, PathKeys } from './client';
export { ApiError, errorMessage, requestIdOf } from './errors';
export { fetchAdminSession, logoutAdminSession } from './auth';
export type { AdminSessionDTO } from './auth';
export { fetchSettingGroup, fetchSettingGroups, resetSettingGroup, updateSettingGroup } from './settings';
export type { SettingFieldDTO, SettingGroupDTO, UpdateSettingGroupInput } from './settings';
export { fetchAuditEntries } from './audit';
export type { AuditEntryDTO, AuditPageDTO, AuditQuery } from './audit';
export { fetchExecutionEntries } from './execution';
export type { ExecutionEntryDTO, ExecutionPageDTO, ExecutionQuery } from './execution';
export { banUser, deleteUser, fetchUser, fetchUsers, unbanUser } from './identity';
export type { BanInput, SubjectDTO, SubjectPageDTO, UserListQuery } from './identity';
export { adjustPoints, createPointsProgram, fetchAdminPointsLedger, fetchPointsAccounts, fetchPointsPrograms, fetchPointsSummary, setPointsProgramStatus, updatePointsProgram } from './points';
export type {
    AdminPointsLedgerQuery,
    AdminPointsViewDTO,
    LedgerEntryDTO,
    PointsAccountAdminDTO,
    PointsAccountPageDTO,
    PointsAdjustInput,
    PointsLedgerPageDTO,
    PointsProgramDTO,
    PointsProgramInput,
    PointsProgramPatch,
    PointsSummaryDTO
} from './points';
export {
    archiveContent,
    createContent,
    fetchContent,
    fetchContentItem,
    fetchReferences,
    purgeContent,
    publishContent,
    rejectContent,
    replaceReferences,
    restoreContent,
    scheduleContent,
    setContentPin,
    submitContent,
    unscheduleContent,
    updateContent
} from './content';
export type { ContentDTO, ContentListQuery, ContentPageDTO, CreateContentInput, PurgeResultDTO, ReferenceDTO, ReplaceReferencesInput, ScheduleContentInput, SetContentPinInput, UpdateContentInput } from './content';
export { archiveTerm, assignTerms, createTerm, fetchDimensions, fetchTargetTerms, fetchTerms, removeTargetTerms, updateTerm } from './taxonomy';
export type { AssignBody, CreateTermInput, DimensionDTO, TargetTermsDTO, TermDTO, UpdateTermInput } from './taxonomy';
export { createUploadIntent, deleteAsset, fetchAsset, fetchAssets, fetchConfiguredBuckets, finalizeUpload, registerExternalAsset, updateAssetMetadata, uploadToProvider } from './assets';
export type { AssetListQuery, AssetPageDTO, AssetRefDTO, ConfiguredBucketsDTO, CreateUploadIntentInput, CreateUploadIntentResult, FinalizeResultDTO, RegisterExternalAssetInput, UpdateAssetMetadataInput } from './assets';
export { fetchDashboard } from './dashboard';
export type { AdminDashboardDTO, DashboardWindow } from './dashboard';
export { assignRole, createRole, deleteRole, fetchCapabilities, fetchRoles, fetchSubjectRoles, replaceRoleCapabilities, revokeRole } from './access';
export type { AssignRoleBody, CapabilityDTO, CreateRoleBody, GrantSummary, ReplaceCapabilitiesBody, RoleDTO } from './access';
export { cancelSubscription, createMembershipLevel, fetchMembershipLevels, fetchMembershipSummary, fetchSubscriptionRenewals, fetchSubscriptions, setMembershipLevelStatus, terminateSubscription, updateMembershipLevel } from './membership';
export type { CancelInput, CreateLevelInput, LevelDTO, MembershipSummaryDTO, RenewalPageDTO, RenewalQuery, SubscriptionDTO, SubscriptionPageDTO, SubscriptionQuery, TerminateInput, UpdateLevelInput } from './membership';
export {
    cancelGiftCardRedemption,
    closeGiftCardBatch,
    commitGiftCardRedemption,
    fetchGiftCardBatches,
    fetchGiftCardRedemption,
    fetchGiftCards,
    generateGiftCardBatch,
    recordGiftCardProviderFact,
    reserveGiftCardRedemption,
    revokeGiftCard,
    verifyGiftCard
} from './gift-cards';
export type {
    BatchPageDTO,
    CancelGiftCardRedemptionInput,
    CardPageDTO,
    CommitGiftCardRedemptionInput,
    GenerateGiftCardBatchInput,
    GiftCardBatchDTO,
    GiftCardBatchQuery,
    GiftCardBatchResultDTO,
    GiftCardDTO,
    GiftCardVerifyDTO,
    ProviderPurchaseInput,
    ReserveGiftCardRedemptionInput,
    VerifyGiftCardInput
} from './gift-cards';
export { disableOidcClient, enableOidcClient, fetchOidcClient, fetchOidcClients, registerOidcClient, rotateOidcClientSecret, updateOidcClient } from './oidc-admin';
export type { ClientDTO, ClientRegistrationResult, RegisterClientBody, UpdateClientBody } from './oidc-admin';
export { approveComment, deleteComment, fetchComment, fetchComments, rejectComment } from './comments';
export type { CommentDTO, CommentPageDTO, CommentQuery, DeleteCommentInput, RejectCommentInput } from './comments';
export {
    approvePost,
    archiveDiscussion,
    archiveTag,
    createTag,
    deletePost,
    fetchDiscussion,
    fetchDiscussions,
    fetchPosts,
    fetchTags,
    hideDiscussion,
    hidePost,
    lockDiscussion,
    publishDiscussion,
    replaceDiscussionTags,
    reorderTags,
    restoreDiscussion,
    restoreTag,
    unlockDiscussion,
    updateTag
} from './community';
export type { CreateTagInput, DiscussionDTO, DiscussionPageDTO, DiscussionQuery, PostDTO, PostPageDTO, PostQuery, ReorderTagsInput, ReplaceDiscussionTagsInput, TagDTO, UpdateTagInput } from './community';
export { cancelNotificationDelivery, fetchNotificationDeliveries, fetchNotificationDelivery, retryNotificationDelivery } from './notifications';
export type { NotificationDeliveryDetailDTO, NotificationDeliveryDTO, NotificationDeliveryPageDTO, NotificationDeliveryQuery, NotificationDeliveryRecordDTO } from './notifications';
