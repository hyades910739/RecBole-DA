# -*- coding: utf-8 -*-
# @Author : Yupeng Hou
# @Email  : houyupeng@ruc.edu.cn
# @File   : sampler.py

# UPDATE
# @Time   : 2020/8/17, 2020/8/31, 2020/10/6, 2020/9/18, 2021/3/19
# @Author : Xingyu Pan, Kaiyuan Li, Yupeng Hou, Yushuo Chen, Zhichao Feng
# @email  : panxy@ruc.edu.cn, tsotfsk@outlook.com, houyupeng@ruc.edu.cn, chenyushuo@ruc.edu.cn, fzcbupt@gmail.com

"""
recbole.sampler
########################
"""

import copy

import numpy as np
import torch


class AbstractSampler(object):
    """:class:`AbstractSampler` is a abstract class, all sampler should inherit from it. This sampler supports returning
    a certain number of random value_ids according to the input key_id, and it also supports to prohibit
    certain key-value pairs by setting used_ids. Besides, in order to improve efficiency, we use :attr:`random_pr`
    to move around the :attr:`random_list` to generate random numbers, so we need to implement the
    :meth:`get_random_list` method in the subclass.

    Args:
        distribution (str): The string of distribution, which is used for subclass.

    Attributes:
        random_list (list or numpy.ndarray): The shuffled result of :meth:`get_random_list`.
        used_ids (numpy.ndarray): The result of :meth:`get_used_ids`.
    """

    def __init__(self, distribution):
        self.distribution = ''
        self.random_list = []
        self.random_pr = 0
        self.random_list_length = 0
        self.set_distribution(distribution)
        self.used_ids = self.get_used_ids()

    def set_distribution(self, distribution):
        """Set the distribution of sampler.

        Args:
            distribution (str): Distribution of the negative items.
        """
        if self.distribution == distribution:
            return
        self.distribution = distribution
        self.random_list = self.get_random_list()
        np.random.shuffle(self.random_list)
        self.random_pr = 0
        self.random_list_length = len(self.random_list)

    def get_random_list(self):
        """
        Returns:
            numpy.ndarray or list: Random list of value_id.
        """
        raise NotImplementedError('method [get_random_list] should be implemented')

    def get_used_ids(self):
        """
        Returns:
            numpy.ndarray: Used ids. Index is key_id, and element is a set of value_ids.
        """
        raise NotImplementedError('method [get_used_ids] should be implemented')

    def random(self):
        """
        Returns:
            value_id (int): Random value_id. Generated by :attr:`random_list`.
        """
        value_id = self.random_list[self.random_pr % self.random_list_length]
        self.random_pr += 1
        return value_id

    def random_num(self, num):
        """
        Args:
            num (int): Number of random value_ids.

        Returns:
            value_ids (numpy.ndarray): Random value_ids. Generated by :attr:`random_list`.
        """
        value_id = []
        self.random_pr %= self.random_list_length
        while True:
            if self.random_pr + num <= self.random_list_length:
                value_id.append(self.random_list[self.random_pr:self.random_pr + num])
                self.random_pr += num
                break
            else:
                value_id.append(self.random_list[self.random_pr:])
                num -= self.random_list_length - self.random_pr
                self.random_pr = 0
        return np.concatenate(value_id)

    def sample_by_key_ids(self, key_ids, num):
        """Sampling by key_ids.

        Args:
            key_ids (numpy.ndarray or list): Input key_ids.
            num (int): Number of sampled value_ids for each key_id.

        Returns:
            torch.tensor: Sampled value_ids.
            value_ids[0], value_ids[len(key_ids)], value_ids[len(key_ids) * 2], ..., value_id[len(key_ids) * (num - 1)]
            is sampled for key_ids[0];
            value_ids[1], value_ids[len(key_ids) + 1], value_ids[len(key_ids) * 2 + 1], ...,
            value_id[len(key_ids) * (num - 1) + 1] is sampled for key_ids[1]; ...; and so on.
        """
        key_ids = np.array(key_ids)
        key_num = len(key_ids)
        total_num = key_num * num
        if (key_ids == key_ids[0]).all():
            key_id = key_ids[0]
            used = np.array(list(self.used_ids[key_id]))
            value_ids = self.random_num(total_num)
            check_list = np.arange(total_num)[np.isin(value_ids, used)]
            while len(check_list) > 0:
                value_ids[check_list] = value = self.random_num(len(check_list))
                perm = value.argsort(kind='quicksort')
                aux = value[perm]
                mask = np.empty(aux.shape, dtype=np.bool_)
                mask[:1] = True
                mask[1:] = aux[1:] != aux[:-1]
                value = aux[mask]
                rev_idx = np.empty(mask.shape, dtype=np.intp)
                rev_idx[perm] = np.cumsum(mask) - 1
                ar = np.concatenate((value, used))
                order = ar.argsort(kind='mergesort')
                sar = ar[order]
                bool_ar = (sar[1:] == sar[:-1])
                flag = np.concatenate((bool_ar, [False]))
                ret = np.empty(ar.shape, dtype=bool)
                ret[order] = flag
                mask = ret[rev_idx]
                check_list = check_list[mask]
        else:
            value_ids = np.zeros(total_num, dtype=np.int64)
            check_list = np.arange(total_num)
            key_ids = np.tile(key_ids, num)
            while len(check_list) > 0:
                value_ids[check_list] = self.random_num(len(check_list))
                check_list = np.array([
                    i for i, used, v in zip(check_list, self.used_ids[key_ids[check_list]], value_ids[check_list])
                    if v in used
                ])
        return torch.tensor(value_ids)


class Sampler(AbstractSampler):
    """:class:`Sampler` is used to sample negative items for each input user. In order to avoid positive items
    in train-phase to be sampled in valid-phase, and positive items in train-phase or valid-phase to be sampled
    in test-phase, we need to input the datasets of all phases for pre-processing. And, before using this sampler,
    it is needed to call :meth:`set_phase` to get the sampler of corresponding phase.

    Args:
        phases (str or list of str): All the phases of input.
        datasets (Dataset or list of Dataset): All the dataset for each phase.
        distribution (str, optional): Distribution of the negative items. Defaults to 'uniform'.

    Attributes:
        phase (str): the phase of sampler. It will not be set until :meth:`set_phase` is called.
    """

    def __init__(self, phases, datasets, distribution='uniform'):
        if not isinstance(phases, list):
            phases = [phases]
        if not isinstance(datasets, list):
            datasets = [datasets]
        if len(phases) != len(datasets):
            raise ValueError(f'Phases {phases} and datasets {datasets} should have the same length.')

        self.phases = phases
        self.datasets = datasets

        self.uid_field = datasets[0].uid_field
        self.iid_field = datasets[0].iid_field

        self.n_users = datasets[0].user_num
        self.n_items = datasets[0].item_num

        super().__init__(distribution=distribution)

    def get_random_list(self):
        """
        Returns:
            numpy.ndarray or list: Random list of item_id.
        """
        if self.distribution == 'uniform':
            return np.arange(1, self.n_items)
        elif self.distribution == 'popularity':
            random_item_list = []
            for dataset in self.datasets:
                random_item_list.extend(dataset.inter_feat[self.iid_field].numpy())
            return random_item_list
        else:
            raise NotImplementedError(f'Distribution [{self.distribution}] has not been implemented.')

    def get_used_ids(self):
        """
        Returns:
            dict: Used item_ids is the same as positive item_ids.
            Key is phase, and value is a numpy.ndarray which index is user_id, and element is a set of item_ids.
        """
        used_item_id = dict()
        last = [set() for _ in range(self.n_users)]
        for phase, dataset in zip(self.phases, self.datasets):
            cur = np.array([set(s) for s in last])
            for uid, iid in zip(dataset.inter_feat[self.uid_field].numpy(), dataset.inter_feat[self.iid_field].numpy()):
                cur[uid].add(iid)
            last = used_item_id[phase] = cur

        for used_item_set in used_item_id[self.phases[-1]]:
            if len(used_item_set) + 1 == self.n_items:  # [pad] is a item.
                raise ValueError(
                    'Some users have interacted with all items, '
                    'which we can not sample negative items for them. '
                    'Please set `max_user_inter_num` to filter those users.'
                )
        return used_item_id

    def set_phase(self, phase):
        """Get the sampler of corresponding phase.

        Args:
            phase (str): The phase of new sampler.

        Returns:
            Sampler: the copy of this sampler, :attr:`phase` is set the same as input phase, and :attr:`used_ids`
            is set to the value of corresponding phase.
        """
        if phase not in self.phases:
            raise ValueError(f'Phase [{phase}] not exist.')
        new_sampler = copy.copy(self)
        new_sampler.phase = phase
        new_sampler.used_ids = new_sampler.used_ids[phase]
        return new_sampler

    def sample_by_user_ids(self, user_ids, num):
        """Sampling by user_ids.

        Args:
            user_ids (numpy.ndarray or list): Input user_ids.
            num (int): Number of sampled item_ids for each user_id.

        Returns:
            torch.tensor: Sampled item_ids.
            item_ids[0], item_ids[len(user_ids)], item_ids[len(user_ids) * 2], ..., item_id[len(user_ids) * (num - 1)]
            is sampled for user_ids[0];
            item_ids[1], item_ids[len(user_ids) + 1], item_ids[len(user_ids) * 2 + 1], ...,
            item_id[len(user_ids) * (num - 1) + 1] is sampled for user_ids[1]; ...; and so on.
        """
        try:
            return self.sample_by_key_ids(user_ids, num)
        except IndexError:
            for user_id in user_ids:
                if user_id < 0 or user_id >= self.n_users:
                    raise ValueError(f'user_id [{user_id}] not exist.')


class KGSampler(AbstractSampler):
    """:class:`KGSampler` is used to sample negative entities in a knowledge graph.

    Args:
        dataset (Dataset): The knowledge graph dataset, which contains triplets in a knowledge graph.
        distribution (str, optional): Distribution of the negative entities. Defaults to 'uniform'.
    """

    def __init__(self, dataset, distribution='uniform'):
        self.dataset = dataset

        self.hid_field = dataset.head_entity_field
        self.tid_field = dataset.tail_entity_field
        self.hid_list = dataset.head_entities
        self.tid_list = dataset.tail_entities

        self.head_entities = set(dataset.head_entities)
        self.entity_num = dataset.entity_num

        super().__init__(distribution=distribution)

    def get_random_list(self):
        """
        Returns:
            numpy.ndarray or list: Random list of entity_id.
        """
        if self.distribution == 'uniform':
            return np.arange(1, self.entity_num)
        elif self.distribution == 'popularity':
            return list(self.hid_list) + list(self.tid_list)
        else:
            raise NotImplementedError(f'Distribution [{self.distribution}] has not been implemented.')

    def get_used_ids(self):
        """
        Returns:
            numpy.ndarray: Used entity_ids is the same as tail_entity_ids in knowledge graph.
            Index is head_entity_id, and element is a set of tail_entity_ids.
        """
        used_tail_entity_id = np.array([set() for _ in range(self.entity_num)])
        for hid, tid in zip(self.hid_list, self.tid_list):
            used_tail_entity_id[hid].add(tid)

        for used_tail_set in used_tail_entity_id:
            if len(used_tail_set) + 1 == self.entity_num:  # [pad] is a entity.
                raise ValueError(
                    'Some head entities have relation with all entities, '
                    'which we can not sample negative entities for them.'
                )
        return used_tail_entity_id

    def sample_by_entity_ids(self, head_entity_ids, num=1):
        """Sampling by head_entity_ids.

        Args:
            head_entity_ids (numpy.ndarray or list): Input head_entity_ids.
            num (int, optional): Number of sampled entity_ids for each head_entity_id. Defaults to ``1``.

        Returns:
            torch.tensor: Sampled entity_ids.
            entity_ids[0], entity_ids[len(head_entity_ids)], entity_ids[len(head_entity_ids) * 2], ...,
            entity_id[len(head_entity_ids) * (num - 1)] is sampled for head_entity_ids[0];
            entity_ids[1], entity_ids[len(head_entity_ids) + 1], entity_ids[len(head_entity_ids) * 2 + 1], ...,
            entity_id[len(head_entity_ids) * (num - 1) + 1] is sampled for head_entity_ids[1]; ...; and so on.
        """
        try:
            return self.sample_by_key_ids(head_entity_ids, num)
        except IndexError:
            for head_entity_id in head_entity_ids:
                if head_entity_id not in self.head_entities:
                    raise ValueError(f'head_entity_id [{head_entity_id}] not exist.')


class RepeatableSampler(AbstractSampler):
    """:class:`RepeatableSampler` is used to sample negative items for each input user. The difference from
    :class:`Sampler` is it can only sampling the items that have not appeared at all phases.

    Args:
        phases (str or list of str): All the phases of input.
        dataset (Dataset): The union of all datasets for each phase.
        distribution (str, optional): Distribution of the negative items. Defaults to 'uniform'.

    Attributes:
        phase (str): the phase of sampler. It will not be set until :meth:`set_phase` is called.
    """

    def __init__(self, phases, dataset, distribution='uniform'):
        if not isinstance(phases, list):
            phases = [phases]
        self.phases = phases
        self.dataset = dataset

        self.iid_field = dataset.iid_field
        self.n_users = dataset.user_num
        self.n_items = dataset.item_num

        super().__init__(distribution=distribution)

    def get_random_list(self):
        """
        Returns:
            numpy.ndarray or list: Random list of item_id.
        """
        if self.distribution == 'uniform':
            return np.arange(1, self.n_items)
        elif self.distribution == 'popularity':
            return self.dataset.inter_feat[self.iid_field].numpy()
        else:
            raise NotImplementedError(f'Distribution [{self.distribution}] has not been implemented.')

    def get_used_ids(self):
        """
        Returns:
            numpy.ndarray: Used item_ids is the same as positive item_ids.
            Index is user_id, and element is a set of item_ids.
        """
        return np.array([set() for _ in range(self.n_users)])

    def sample_by_user_ids(self, user_ids, num):
        """Sampling by user_ids.

        Args:
            user_ids (numpy.ndarray or list): Input user_ids.
            num (int): Number of sampled item_ids for each user_id.

        Returns:
            torch.tensor: Sampled item_ids.
            item_ids[0], item_ids[len(user_ids)], item_ids[len(user_ids) * 2], ..., item_id[len(user_ids) * (num - 1)]
            is sampled for user_ids[0];
            item_ids[1], item_ids[len(user_ids) + 1], item_ids[len(user_ids) * 2 + 1], ...,
            item_id[len(user_ids) * (num - 1) + 1] is sampled for user_ids[1]; ...; and so on.
        """
        try:
            return self.sample_by_key_ids(user_ids, num)
        except IndexError:
            for user_id in user_ids:
                if user_id < 0 or user_id >= self.n_users:
                    raise ValueError(f'user_id [{user_id}] not exist.')

    def set_phase(self, phase):
        """Get the sampler of corresponding phase.

        Args:
            phase (str): The phase of new sampler.

        Returns:
            Sampler: the copy of this sampler, and :attr:`phase` is set the same as input phase.
        """
        if phase not in self.phases:
            raise ValueError(f'Phase [{phase}] not exist.')
        new_sampler = copy.copy(self)
        new_sampler.phase = phase
        return new_sampler


class SeqSampler(AbstractSampler):
    """:class:`SeqSampler` is used to sample negative item sequence.

        Args:
            datasets (Dataset or list of Dataset): All the dataset for each phase.
            distribution (str, optional): Distribution of the negative items. Defaults to 'uniform'.
    """

    def __init__(self, dataset, distribution='uniform'):
        self.dataset = dataset

        self.iid_field = dataset.iid_field
        self.n_users = dataset.user_num
        self.n_items = dataset.item_num

        super().__init__(distribution=distribution)

    def get_used_ids(self):
        pass

    def get_random_list(self):
        """
        Returns:
            numpy.ndarray or list: Random list of item_id.
        """
        return np.arange(1, self.n_items)

    def sample_neg_sequence(self, pos_sequence):
        """For each moment, sampling one item from all the items except the one the user clicked on at that moment.

        Args:
            pos_sequence (torch.Tensor):  all users' item history sequence, with the shape of `(N, )`.

        Returns:
            torch.tensor : all users' negative item history sequence.

        """
        total_num = len(pos_sequence)
        value_ids = np.zeros(total_num, dtype=np.int64)
        check_list = np.arange(total_num)
        while len(check_list) > 0:
            value_ids[check_list] = self.random_num(len(check_list))
            check_index = np.where(value_ids[check_list] == pos_sequence[check_list])
            check_list = check_list[check_index]

        return torch.tensor(value_ids)
