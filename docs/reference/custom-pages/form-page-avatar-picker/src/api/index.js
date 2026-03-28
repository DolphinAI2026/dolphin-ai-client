const api = {
  // 查询人员列表（带头像）
  QUERY_USERS: {
    url: "/custom/avatar/users",
    method: "POST",
    disableSuccessMsg: true,
  },
  // 上传头像
  UPLOAD_AVATAR: {
    url: "/custom/avatar/upload",
    method: "POST",
    disableSuccessMsg: true,
  },
};

export default api;
